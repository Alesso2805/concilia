import { BarChart } from 'echarts/charts';
import { AriaComponent, GridComponent, TooltipComponent } from 'echarts/components';
import * as echarts from 'echarts/core';
import { SVGRenderer } from 'echarts/renderers';

// Only what the reports use, so the rest of ECharts stays out of the bundle (ADR-0007).
echarts.use([BarChart, AriaComponent, GridComponent, TooltipComponent, SVGRenderer]);

export { echarts };
