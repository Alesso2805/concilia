from alembic import op

revision = "0009"
down_revision = "0008"

TENANT = "NULLIF(current_setting('app.org_id', true), '')::uuid"
TABLES = ("engine_runs", "matches", "match_items", "match_decisions")
REASONS = "('commission', 'detraction', 'rounding', 'overpayment', 'other')"

STATEMENTS = [
    """
    CREATE TABLE engine_runs (
        id uuid PRIMARY KEY,
        organization_id uuid NOT NULL REFERENCES organizations (id),
        bank_account_id uuid NOT NULL,
        period date NOT NULL CHECK (period = date_trunc('month', period)::date),
        job_id uuid UNIQUE,
        rules_version integer NOT NULL CHECK (rules_version > 0),
        proposals_count integer CHECK (proposals_count >= 0),
        started_at timestamptz NOT NULL,
        finished_at timestamptz,
        UNIQUE (organization_id, id),
        FOREIGN KEY (organization_id, bank_account_id)
            REFERENCES bank_accounts (organization_id, id),
        CHECK ((finished_at IS NULL) = (proposals_count IS NULL))
    )
    """,
    f"""
    CREATE TABLE matches (
        id uuid PRIMARY KEY,
        organization_id uuid NOT NULL REFERENCES organizations (id),
        bank_account_id uuid NOT NULL,
        source text NOT NULL CHECK (source IN ('engine', 'ai', 'manual')),
        rule text CHECK (rule IN ('R1', 'R2', 'R3', 'R4', 'R5', 'R6')),
        score smallint CHECK (score BETWEEN 0 AND 100),
        suggested_difference_reason text CHECK (suggested_difference_reason IN {REASONS}),
        explanation text CHECK (length(explanation) BETWEEN 1 AND 500),
        engine_run_id uuid,
        ai_suggestion_id uuid,
        created_by uuid,
        created_at timestamptz NOT NULL,
        UNIQUE (organization_id, id),
        FOREIGN KEY (organization_id, bank_account_id)
            REFERENCES bank_accounts (organization_id, id),
        FOREIGN KEY (organization_id, engine_run_id) REFERENCES engine_runs (organization_id, id),
        FOREIGN KEY (organization_id, created_by) REFERENCES memberships (organization_id, user_id),
        CHECK ((source = 'engine') = (rule IS NOT NULL AND score IS NOT NULL
                                      AND engine_run_id IS NOT NULL AND created_by IS NULL)),
        CHECK ((source = 'ai') = (ai_suggestion_id IS NOT NULL)),
        CHECK (source = 'engine' OR (rule IS NULL AND score IS NULL AND engine_run_id IS NULL
                                     AND created_by IS NOT NULL)),
        CHECK (source <> 'engine' OR explanation IS NOT NULL)
    )
    """,
    "CREATE INDEX matches_account_idx ON matches (bank_account_id, created_at, id)",
    "CREATE INDEX matches_run_idx ON matches (engine_run_id)",
    """
    CREATE TABLE match_items (
        id uuid PRIMARY KEY,
        organization_id uuid NOT NULL REFERENCES organizations (id),
        match_id uuid NOT NULL,
        bank_movement_id uuid,
        receivable_id uuid,
        applied_cents bigint,
        UNIQUE (organization_id, id),
        UNIQUE (match_id, bank_movement_id),
        UNIQUE (match_id, receivable_id),
        FOREIGN KEY (organization_id, match_id) REFERENCES matches (organization_id, id),
        FOREIGN KEY (organization_id, bank_movement_id)
            REFERENCES bank_movements (organization_id, id),
        FOREIGN KEY (organization_id, receivable_id) REFERENCES receivables (organization_id, id),
        CHECK ((bank_movement_id IS NULL) <> (receivable_id IS NULL)),
        CHECK (CASE WHEN receivable_id IS NULL THEN applied_cents IS NULL
                    ELSE applied_cents > 0 END)
    )
    """,
    "CREATE INDEX match_items_movement_idx ON match_items (bank_movement_id)",
    "CREATE INDEX match_items_receivable_idx ON match_items (receivable_id)",
    f"""
    CREATE TABLE match_decisions (
        id uuid PRIMARY KEY,
        seq bigint GENERATED ALWAYS AS IDENTITY,
        organization_id uuid NOT NULL REFERENCES organizations (id),
        match_id uuid NOT NULL,
        action text NOT NULL
            CHECK (action IN ('confirm', 'discard', 'approve', 'reject', 'revert')),
        reason text CHECK (length(reason) BETWEEN 1 AND 500),
        difference_reason text CHECK (difference_reason IN {REASONS}),
        difference_note text CHECK (length(difference_note) BETWEEN 1 AND 500),
        decided_by uuid NOT NULL,
        decided_at timestamptz NOT NULL,
        UNIQUE (organization_id, id),
        UNIQUE (match_id, action),
        FOREIGN KEY (organization_id, match_id) REFERENCES matches (organization_id, id),
        FOREIGN KEY (organization_id, decided_by)
            REFERENCES memberships (organization_id, user_id),
        CHECK (action NOT IN ('reject', 'revert') OR reason IS NOT NULL),
        CHECK (action = 'confirm' OR (difference_reason IS NULL AND difference_note IS NULL)),
        CHECK ((coalesce(difference_reason, '') = 'other') = (difference_note IS NOT NULL))
    )
    """,
    "CREATE INDEX match_decisions_match_idx ON match_decisions (match_id, seq)",
    *(
        statement
        for table in TABLES
        for statement in (
            f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
            f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
            f"""
            CREATE POLICY organization_isolation ON {table}
                USING (organization_id = {TENANT}) WITH CHECK (organization_id = {TENANT})
            """,
            f"GRANT SELECT, INSERT ON {table} TO concilia_app, concilia_worker",
        )
    ),
    """
    GRANT UPDATE (proposals_count, finished_at) ON engine_runs TO concilia_app, concilia_worker
    """,
    """
    CREATE VIEW match_status WITH (security_invoker = true) AS
    SELECT m.id AS match_id, m.organization_id, m.bank_account_id,
           CASE d.action
               WHEN 'confirm' THEN 'confirmed'
               WHEN 'discard' THEN 'discarded'
               WHEN 'approve' THEN 'approved'
               WHEN 'reject' THEN 'rejected'
               WHEN 'revert' THEN 'reverted'
               ELSE 'proposed'
           END AS status,
           coalesce(d.decided_at, m.created_at) AS status_at
    FROM matches m
    LEFT JOIN LATERAL (
        SELECT action, decided_at FROM match_decisions
        WHERE match_id = m.id ORDER BY seq DESC LIMIT 1
    ) d ON true
    """,
    """
    CREATE VIEW receivable_balances WITH (security_invoker = true) AS
    SELECT r.id AS receivable_id, r.organization_id, r.amount_cents,
           r.amount_cents
               - coalesce(sum(i.applied_cents) FILTER (WHERE s.status = 'approved'), 0)
               AS open_cents,
           r.amount_cents
               - coalesce(sum(i.applied_cents)
                          FILTER (WHERE s.status IN ('proposed', 'confirmed', 'approved')), 0)
               AS available_cents
    FROM receivables r
    LEFT JOIN match_items i ON i.receivable_id = r.id
    LEFT JOIN match_status s ON s.match_id = i.match_id
    GROUP BY r.id
    """,
    "GRANT SELECT ON match_status, receivable_balances TO concilia_app, concilia_worker",
    """
    CREATE FUNCTION match_items_check() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
    DECLARE
        v_account uuid;
    BEGIN
        IF EXISTS (SELECT 1 FROM match_decisions WHERE match_id = NEW.match_id) THEN
            RAISE EXCEPTION 'match_already_decided' USING ERRCODE = 'check_violation';
        END IF;
        SELECT bank_account_id INTO v_account FROM matches WHERE id = NEW.match_id;
        IF NEW.bank_movement_id IS NOT NULL THEN
            IF NOT EXISTS (
                SELECT 1 FROM bank_movements
                WHERE id = NEW.bank_movement_id AND bank_account_id = v_account
                  AND amount_cents > 0 AND voided_at IS NULL
            ) THEN
                RAISE EXCEPTION 'not_a_live_credit_of_the_account'
                    USING ERRCODE = 'check_violation';
            END IF;
            IF EXISTS (
                SELECT 1 FROM match_items i JOIN match_status s ON s.match_id = i.match_id
                WHERE i.bank_movement_id = NEW.bank_movement_id AND i.match_id <> NEW.match_id
                  AND s.status IN ('proposed', 'confirmed', 'approved')
            ) THEN
                RAISE EXCEPTION 'credit_in_active_match' USING ERRCODE = 'check_violation';
            END IF;
        ELSE
            IF NOT EXISTS (
                SELECT 1 FROM receivables WHERE id = NEW.receivable_id AND cancelled_at IS NULL
            ) THEN
                RAISE EXCEPTION 'receivable_cancelled' USING ERRCODE = 'check_violation';
            END IF;
            IF NEW.applied_cents > (
                SELECT available_cents FROM receivable_balances
                WHERE receivable_id = NEW.receivable_id
            ) THEN
                RAISE EXCEPTION 'applied_exceeds_available' USING ERRCODE = 'check_violation';
            END IF;
        END IF;
        RETURN NEW;
    END
    $$
    """,
    """
    CREATE TRIGGER match_items_check BEFORE INSERT ON match_items
        FOR EACH ROW EXECUTE FUNCTION match_items_check()
    """,
    """
    CREATE FUNCTION matches_complete() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM match_items WHERE match_id = NEW.id AND bank_movement_id IS NOT NULL
        ) OR NOT EXISTS (
            SELECT 1 FROM match_items WHERE match_id = NEW.id AND receivable_id IS NOT NULL
        ) THEN
            RAISE EXCEPTION 'match_needs_a_credit_and_a_receivable'
                USING ERRCODE = 'check_violation';
        END IF;
        RETURN NULL;
    END
    $$
    """,
    """
    CREATE CONSTRAINT TRIGGER matches_complete AFTER INSERT ON matches
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION matches_complete()
    """,
    """
    CREATE FUNCTION match_decisions_check() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
    DECLARE
        v_status text;
        v_created_by uuid;
        v_confirmed_by uuid;
        v_difference bigint;
    BEGIN
        SELECT status INTO v_status FROM match_status WHERE match_id = NEW.match_id;
        IF NOT (
            (v_status = 'proposed' AND NEW.action IN ('confirm', 'discard'))
            OR (v_status = 'confirmed' AND NEW.action IN ('approve', 'reject'))
            OR (v_status = 'approved' AND NEW.action = 'revert')
        ) THEN
            RAISE EXCEPTION 'invalid_transition' USING ERRCODE = 'check_violation';
        END IF;
        IF EXISTS (
            SELECT 1 FROM match_items i
            JOIN bank_movements b ON b.id = i.bank_movement_id
            JOIN period_status p ON p.bank_account_id = b.bank_account_id
                                AND p.period = date_trunc('month', b.booked_on)::date
            WHERE i.match_id = NEW.match_id AND p.closed
        ) THEN
            RAISE EXCEPTION 'closed_period' USING ERRCODE = 'check_violation';
        END IF;
        IF NEW.action IN ('approve', 'reject', 'revert') THEN
            SELECT created_by INTO v_created_by FROM matches WHERE id = NEW.match_id;
            SELECT decided_by INTO v_confirmed_by FROM match_decisions
            WHERE match_id = NEW.match_id AND action = 'confirm';
            IF NEW.decided_by = v_created_by OR NEW.decided_by = v_confirmed_by THEN
                RAISE EXCEPTION 'four_eyes' USING ERRCODE = 'check_violation';
            END IF;
        END IF;
        IF NEW.action = 'confirm' THEN
            SELECT coalesce(sum(b.amount_cents), 0) - coalesce(sum(i.applied_cents), 0)
            INTO v_difference
            FROM match_items i LEFT JOIN bank_movements b ON b.id = i.bank_movement_id
            WHERE i.match_id = NEW.match_id;
            IF (v_difference <> 0) <> (NEW.difference_reason IS NOT NULL) THEN
                RAISE EXCEPTION 'difference_reason_mismatch' USING ERRCODE = 'check_violation';
            END IF;
            IF NEW.difference_reason = 'overpayment' AND v_difference <= 0 THEN
                RAISE EXCEPTION 'overpayment_not_positive' USING ERRCODE = 'check_violation';
            END IF;
        END IF;
        RETURN NEW;
    END
    $$
    """,
    """
    CREATE TRIGGER match_decisions_check BEFORE INSERT ON match_decisions
        FOR EACH ROW EXECUTE FUNCTION match_decisions_check()
    """,
]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    raise NotImplementedError("migrations are forward-only")
