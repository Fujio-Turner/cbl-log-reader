# Chart.js → Apache ECharts Migration Plan

## Overview
Migrate all charts from Chart.js (+ zoom/annotation plugins) to Apache ECharts. This gives us native heatmap, treemap, Gantt (custom series), built-in dataZoom, and markLine (replaces stakes/annotations).

---

## Phase 1: Swap Libraries in `index.html`

### Remove (lines 13–16, 218–219):
```html
<!-- REMOVE these -->
<script src="https://cdn.jsdelivr.net/npm/moment@2.29.4/moment.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-moment@1.0.0/dist/chartjs-adapter-moment.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-zoom@2.0.1/dist/chartjs-plugin-zoom.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-annotation@3.0.1/dist/chartjs-plugin-annotation.min.js"></script>
```

### Add:
```html
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
```

### Replace `<canvas>` with `<div>` for all charts:
ECharts uses `<div>` containers, not `<canvas>`. Replace every:
```html
<canvas id="lineChart"></canvas>
```
with:
```html
<div id="lineChart" style="width:100%;height:100%;"></div>
```

**All chart IDs to convert:**
- `lineChart` (main line chart)
- `pieChart`
- `topNChart`
- `stackedBarChart`
- `errorRateChart`
- `treemapChart`
- `syncTimelineChart`
- `syncGanttChart`

**Keep as-is:** `heatmapContainer` — convert from HTML table to ECharts native heatmap inside a `<div>`.

### Remove zoom buttons (lines 94–99):
ECharts has built-in `dataZoom` and `toolbox` — remove the manual zoom-out/reset/zoom-in buttons:
```html
<!-- REMOVE -->
<div class="join">
    <button id="zoom-out" ...>−</button>
    <button id="zoom-reset" ...>⌂</button>
    <button id="zoom-in" ...>+</button>
</div>
```
The `📅 Use Chart's X-Axis Values` button stays — update its JS to read from ECharts axis.

---

## Phase 2: Migrate `scripts.js` — Globals & Init

### Current globals to replace:
```js
// OLD
let lineChart, pieChart, topNChart, errorRateChart, stackedBarChart, treemapChart, syncTimelineChart, syncGanttChart;
```
```js
// NEW — ECharts instances
let lineChart, pieChart, topNChart, errorRateChart, stackedBarChart, treemapChart, syncTimelineChart, syncGanttChart, heatmapChart;
```

### ECharts init pattern:
Each chart init changes from `new Chart(ctx, {...})` to:
```js
// Dispose previous instance if exists, then create new
if (lineChart) lineChart.dispose();
lineChart = echarts.init(document.getElementById('lineChart'));
lineChart.setOption({...});
```

### Window resize handler:
Add once in `$(document).ready`:
```js
window.addEventListener('resize', function() {
    [lineChart, pieChart, topNChart, errorRateChart, stackedBarChart, 
     treemapChart, syncTimelineChart, syncGanttChart, heatmapChart]
        .forEach(c => c && c.resize());
});
```

---

## Phase 3: Migrate Each Chart Function

### 3A. `updateLineChart(data, errorFilter)` — Main Line Chart
**Current:** Chart.js line with time x-axis, zoom plugin, annotation plugin for stakes.
**ECharts equivalent:**
```js
function updateLineChart(data, errorFilter) {
    if (!data || data.length === 0) return;

    // Group data by type (same logic as current)
    let datasets = {};
    data.forEach(item => {
        if (!item.second || !item.type || typeof item.count !== 'number') return;
        if (!datasets[item.type]) datasets[item.type] = [];
        datasets[item.type].push([item.second, item.count]);
    });

    let series = Object.keys(datasets).map(type => ({
        name: type,
        type: 'line',
        data: datasets[type].sort((a, b) => a[0].localeCompare(b[0])),
        smooth: 0.1,
        showSymbol: false,
        itemStyle: { color: getTypeColor(type, errorFilter, Object.keys(datasets)) },
        // Stakes will be added as markLine (see Phase 4)
        markLine: { data: [] }
    }));

    let scaleType = $('#scale-mode-toggle').is(':checked') ? 'log' : 'value';

    if (!lineChart) lineChart = echarts.init(document.getElementById('lineChart'));
    lineChart.setOption({
        tooltip: { trigger: 'axis' },
        legend: { type: 'scroll', top: 0 },
        grid: { left: 60, right: 30, top: 50, bottom: 80 },
        xAxis: { type: 'time', name: 'Time' },
        yAxis: { type: scaleType, name: '# of Logs', min: 0 },
        dataZoom: [
            { type: 'slider', xAxisIndex: 0, bottom: 10 },  // replaces zoom plugin
            { type: 'inside', xAxisIndex: 0 }                // drag to zoom
        ],
        toolbox: {
            feature: {
                dataZoom: { yAxisIndex: 'none' },  // box zoom
                restore: {},                        // replaces zoom-reset button
                saveAsImage: {}
            }
        },
        series: series
    }, true); // true = notMerge, full replace
}
```

**Key differences:**
- `dataZoom` replaces chartjs-plugin-zoom (drag, slider, pinch all built-in)
- `toolbox.restore` replaces `#zoom-reset` button
- `markLine` replaces chartjs-plugin-annotation for stakes
- No need for moment.js — ECharts parses time strings natively

### 3B. `updatePieChart(data)`
```js
function updatePieChart(data) {
    if (!data || data.length === 0) return;
    if (!pieChart) pieChart = echarts.init(document.getElementById('pieChart'));
    pieChart.setOption({
        tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
        legend: { type: 'scroll', orient: 'vertical', right: 10, top: 20 },
        series: [{
            type: 'pie',
            radius: ['30%', '70%'],  // donut style
            data: data.map(d => ({
                name: d.type_prefix || 'Unknown',
                value: d.count || 0,
                itemStyle: { color: getTypeColor(d.type_prefix, false, [], true) }
            })),
            emphasis: { itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0,0,0,0.3)' } }
        }]
    }, true);
}
```

### 3C. `updateTopNChart(data)` — Horizontal Bar
```js
function updateTopNChart(data) {
    if (!data || data.length === 0) return;
    let sorted = [...data]
        .filter(d => d && d.type_prefix && typeof d.count === 'number')
        .sort((a, b) => a.count - b.count)  // ascending for horizontal bar (bottom to top)
        .slice(-15);  // top 15

    if (!topNChart) topNChart = echarts.init(document.getElementById('topNChart'));
    topNChart.setOption({
        tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
        grid: { left: 150, right: 30, top: 30, bottom: 30 },
        xAxis: { type: 'value', name: 'Count' },
        yAxis: { type: 'category', data: sorted.map(d => d.type_prefix) },
        series: [{
            type: 'bar',
            data: sorted.map(d => ({
                value: d.count,
                itemStyle: { color: getTypeColor(d.type_prefix, false, [], true) }
            }))
        }]
    }, true);
}
```

### 3D. `updateStackedBarChart(data)`
```js
function updateStackedBarChart(data) {
    if (!data || data.length === 0) return;

    // Aggregate by hour and type (same logic as current)
    let buckets = {};
    let allTypes = new Set();
    data.forEach(item => {
        if (!item.second || !item.type) return;
        let parts = item.second.split(' ');
        if (parts.length < 2) return;
        let hour = parts[0] + ' ' + parts[1].split(':')[0] + ':00';
        allTypes.add(item.type);
        if (!buckets[hour]) buckets[hour] = {};
        buckets[hour][item.type] = (buckets[hour][item.type] || 0) + (item.count || 0);
    });

    let sortedTimes = Object.keys(buckets).sort();
    let typeList = [...allTypes].sort();

    let series = typeList.map(type => ({
        name: type,
        type: 'bar',
        stack: 'total',
        data: sortedTimes.map(t => buckets[t][type] || 0),
        itemStyle: { color: getTypeColor(type, false, [], true) }
    }));

    if (!stackedBarChart) stackedBarChart = echarts.init(document.getElementById('stackedBarChart'));
    stackedBarChart.setOption({
        tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
        legend: { type: 'scroll', top: 0 },
        grid: { left: 60, right: 30, top: 50, bottom: 50 },
        xAxis: { type: 'category', data: sortedTimes, name: 'Hour' },
        yAxis: { type: 'value', name: 'Count' },
        series: series
    }, true);
}
```

### 3E. `updateErrorRateChart(data)` — Dual Axis Line
```js
function updateErrorRateChart(data) {
    if (!data || data.length === 0) return;

    // Same bucketing logic as current
    let buckets = {};
    data.forEach(item => {
        if (!item.second) return;
        if (!buckets[item.second]) buckets[item.second] = { total: 0, errors: 0 };
        buckets[item.second].total += item.count || 0;
        if (item.type === 'Error') buckets[item.second].errors += item.count || 0;
    });

    let times = Object.keys(buckets).sort();
    let rateData = times.map(t => [t, buckets[t].total > 0 ? 
        Math.round((buckets[t].errors / buckets[t].total) * 10000) / 100 : 0]);
    let totalData = times.map(t => [t, buckets[t].total]);
    let errorData = times.map(t => [t, buckets[t].errors]);

    if (!errorRateChart) errorRateChart = echarts.init(document.getElementById('errorRateChart'));
    errorRateChart.setOption({
        tooltip: { trigger: 'axis' },
        legend: { top: 0 },
        grid: { left: 60, right: 60, top: 50, bottom: 30 },
        xAxis: { type: 'time' },
        yAxis: [
            { type: 'value', name: 'Error Rate (%)', max: 100,
              axisLabel: { formatter: '{value}%' } },
            { type: 'value', name: 'Count', position: 'right' }
        ],
        series: [
            { name: 'Error Rate %', type: 'line', data: rateData, yAxisIndex: 0,
              areaStyle: { opacity: 0.1 }, itemStyle: { color: '#DC143C' }, smooth: 0.2 },
            { name: 'Total Logs', type: 'line', data: totalData, yAxisIndex: 1,
              lineStyle: { type: 'dashed' }, itemStyle: { color: '#1E90FF' }, smooth: 0.2, showSymbol: false },
            { name: 'Error Count', type: 'line', data: errorData, yAxisIndex: 1,
              itemStyle: { color: '#000' }, smooth: 0.2, showSymbol: false }
        ],
        // Stakes via markLine on first series (see Phase 4)
    }, true);
}
```

### 3F. `updateHeatmap(data)` — Native ECharts Heatmap
**Replaces the HTML table approach with a real interactive heatmap.**
```js
function updateHeatmap(data) {
    let container = document.getElementById('heatmapContainer');
    if (!container) return;
    if (!data || data.length === 0) {
        container.innerHTML = '<p style="padding:20px;text-align:center;color:#888;">No data</p>';
        return;
    }

    // Aggregate by day × hour (same logic)
    let grid = {};
    let days = new Set();
    data.forEach(item => {
        if (!item.second) return;
        let parts = item.second.split(' ');
        if (parts.length < 2) return;
        let day = parts[0];
        let hour = parseInt(parts[1].split(':')[0], 10);
        days.add(day);
        if (!grid[day]) grid[day] = {};
        grid[day][hour] = (grid[day][hour] || 0) + (item.count || 0);
    });

    let sortedDays = [...days].sort();
    let hours = Array.from({length: 24}, (_, i) => i.toString().padStart(2, '0'));
    let heatData = [];
    let maxVal = 0;
    sortedDays.forEach((day, di) => {
        for (let h = 0; h < 24; h++) {
            let v = (grid[day] && grid[day][h]) || 0;
            heatData.push([h, di, v]);
            if (v > maxVal) maxVal = v;
        }
    });

    // Clear any old HTML content
    container.innerHTML = '';

    if (!heatmapChart) heatmapChart = echarts.init(container);
    heatmapChart.setOption({
        tooltip: {
            formatter: p => `${sortedDays[p.value[1]]} ${hours[p.value[0]]}:00<br/>Count: <b>${p.value[2]}</b>`
        },
        grid: { left: 100, right: 40, top: 20, bottom: 40 },
        xAxis: { type: 'category', data: hours, name: 'Hour', splitArea: { show: true } },
        yAxis: { type: 'category', data: sortedDays, name: 'Date', splitArea: { show: true } },
        visualMap: {
            min: 0, max: maxVal || 1, calculable: true, orient: 'horizontal',
            left: 'center', bottom: 0,
            inRange: { color: ['#f5f5f5', '#d0e8ff', '#1E90FF', '#DC143C'] }
        },
        series: [{
            type: 'heatmap',
            data: heatData,
            label: { show: true, formatter: p => p.value[2] > 0 ? p.value[2] : '' },
            emphasis: { itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0,0,0,0.5)' } }
        }]
    }, true);
}
```

### 3G. `updateTreemapChart(data)` — Native ECharts Treemap
**Replaces the manual canvas-drawn treemap.**
```js
function updateTreemapChart(data) {
    if (!data || data.length === 0) return;

    let sorted = data
        .filter(d => d && d.type_prefix && typeof d.count === 'number' && d.count > 0)
        .sort((a, b) => b.count - a.count);

    if (!treemapChart) treemapChart = echarts.init(document.getElementById('treemapChart'));
    treemapChart.setOption({
        tooltip: { formatter: '{b}: {c}' },
        series: [{
            type: 'treemap',
            data: sorted.map(d => ({
                name: d.type_prefix,
                value: d.count,
                itemStyle: { color: getTypeColor(d.type_prefix, false, [], true) }
            })),
            label: { show: true, formatter: '{b}\n{c}' },
            breadcrumb: { show: false },
            roam: false
        }]
    }, true);
}
```

### 3H. `updateSyncTimeline(logReportData)` — Keep as bar chart
Same as current logic but with ECharts horizontal bar:
```js
function updateSyncTimeline(logReportData) {
    // ... same bar-building logic ...
    if (!syncTimelineChart) syncTimelineChart = echarts.init(document.getElementById('syncTimelineChart'));
    syncTimelineChart.setOption({
        tooltip: { trigger: 'axis' },
        legend: { top: 0 },
        grid: { left: 120, right: 30, top: 50, bottom: 30 },
        yAxis: { type: 'category', data: bars.map((b, i) => `#${i+1} ${b.label}`) },
        xAxis: { type: 'value', name: 'Value' },
        series: [
            { name: 'Duration (sec)', type: 'bar', data: bars.map(b => Math.round((b.end - b.start) / 1000)),
              itemStyle: { color: b => bars[b.dataIndex].hasError ? '#DC143C' : '#1E90FF' } },
            { name: 'Docs Processed', type: 'bar', data: bars.map(b => b.docCount),
              itemStyle: { color: 'rgba(50,205,50,0.7)' } },
            { name: 'Write Rejections', type: 'bar', data: bars.map(b => b.rejectCount),
              itemStyle: { color: 'rgba(255,69,0,0.7)' } }
        ]
    }, true);
}
```

### 3I. `updateSyncGantt(logReportData)` — ECharts Custom Series ⭐
**This is the key chart that didn't work with Chart.js.**
```js
function updateSyncGantt(logReportData) {
    const replicationStats = logReportData?.["replicationStats"] || [];
    if (replicationStats.length === 0) return;

    let sorted = [...replicationStats].sort((a, b) => new Date(a.startTime) - new Date(b.startTime));
    let sessions = [];
    sorted.forEach((entry, i) => {
        if (!entry.startTime) return;
        let start = new Date(entry.startTime).getTime();
        let end = (i + 1 < sorted.length && sorted[i+1].startTime)
            ? new Date(sorted[i+1].startTime).getTime()
            : start + 60000;
        sessions.push({
            pid: `PID:${entry.replicationProcessId || '?'}`,
            start, end,
            docCount: entry.documentsProcessedCount || 0,
            rejectCount: entry.localWriteRejectionCount || 0
        });
    });

    let pids = [...new Set(sessions.map(s => s.pid))].sort();
    let pidColors = {};
    let palette = ['#1E90FF','#32CD32','#FFA500','#9400D3','#FF69B4',
                   '#00CED1','#DC143C','#FFD700','#8A2BE2','#008080'];
    pids.forEach((p, i) => { pidColors[p] = palette[i % palette.length]; });

    // Build data: [categoryIndex, startTime, endTime, duration]
    let ganttData = sessions.map(s => ({
        name: s.pid,
        value: [pids.indexOf(s.pid), s.start, s.end, s.end - s.start],
        itemStyle: { color: pidColors[s.pid] },
        docCount: s.docCount,
        rejectCount: s.rejectCount
    }));

    function renderGanttItem(params, api) {
        let catIndex = api.value(0);
        let start = api.coord([api.value(1), catIndex]);
        let end = api.coord([api.value(2), catIndex]);
        let height = api.size([0, 1])[1] * 0.6;
        let rect = echarts.graphic.clipRectByRect(
            { x: start[0], y: start[1] - height / 2, width: end[0] - start[0], height: height },
            { x: params.coordSys.x, y: params.coordSys.y,
              width: params.coordSys.width, height: params.coordSys.height }
        );
        return rect && {
            type: 'rect',
            transition: ['shape'],
            shape: rect,
            style: api.style()
        };
    }

    if (!syncGanttChart) syncGanttChart = echarts.init(document.getElementById('syncGanttChart'));
    syncGanttChart.setOption({
        tooltip: {
            formatter: function(p) {
                let s = new Date(p.value[1]).toLocaleTimeString();
                let e = new Date(p.value[2]).toLocaleTimeString();
                let dur = Math.round(p.value[3] / 1000);
                let lines = [`<b>${p.name}</b>`, `${s} → ${e}`, `Duration: ${dur}s`];
                if (p.data.docCount) lines.push(`Docs: ${p.data.docCount}`);
                if (p.data.rejectCount) lines.push(`<span style="color:red">Rejections: ${p.data.rejectCount}</span>`);
                return lines.join('<br/>');
            }
        },
        title: { text: 'Sync Sessions Gantt — Concurrent View', left: 'center' },
        grid: { left: 100, right: 30, top: 50, bottom: 60 },
        xAxis: {
            type: 'time',
            min: Math.min(...sessions.map(s => s.start)),
            max: Math.max(...sessions.map(s => s.end)),
            axisLabel: { formatter: val => new Date(val).toLocaleTimeString() }
        },
        yAxis: { type: 'category', data: pids },
        dataZoom: [
            { type: 'slider', xAxisIndex: 0, bottom: 5 },
            { type: 'inside', xAxisIndex: 0 }
        ],
        series: [{
            type: 'custom',
            renderItem: renderGanttItem,
            encode: { x: [1, 2], y: 0 },
            data: ganttData
        }]
    }, true);
}
```

---

## Phase 4: Migrate Stakes (Annotations → markLine)

### Current stake system:
- `addStake()` / `removeStake()` add/remove vertical dashed lines on lineChart and errorRateChart
- Uses `chartjs-plugin-annotation`
- Stakes tracked in `stakes` object: `{ stakeId: { color, timestamp, rowIndex } }`

### ECharts equivalent — `markLine`:
```js
function addStakeToChart(chart, stakeId, timeValue, color, rowIndex) {
    if (!chart) return;
    let option = chart.getOption();
    if (!option.series || !option.series.length) return;

    // Add markLine to first series
    let markData = option.series[0].markLine?.data || [];
    markData.push({
        name: '#' + (rowIndex + 1),
        xAxis: timeValue,
        lineStyle: { color: color, type: 'dashed', width: 2 },
        label: { show: true, formatter: '#' + (rowIndex + 1), color: '#fff',
                 backgroundColor: color, padding: [2, 4], borderRadius: 2 },
        _stakeId: stakeId  // custom property for lookup
    });
    chart.setOption({ series: [{ markLine: { silent: false, symbol: 'none', data: markData } }] });
}

function removeStakeFromChart(chart, stakeId) {
    if (!chart) return;
    let option = chart.getOption();
    if (!option.series || !option.series.length) return;

    let markData = (option.series[0].markLine?.data || []).filter(d => d._stakeId !== stakeId);
    chart.setOption({
        series: [{ markLine: { data: markData } }]
    });
}
```

### Update `addStake` / `removeStake` / `clear-stakes`:
Same as current but call the ECharts versions above instead of the Chart.js annotation versions.

---

## Phase 5: Migrate Chart Controls

### Scale toggle (`#scale-mode-toggle`):
```js
$('#scale-mode-toggle').change(function() {
    if (lineChart) {
        let type = $(this).is(':checked') ? 'log' : 'value';
        lineChart.setOption({ yAxis: { type: type } });
    }
});
```

### Use Chart's X-Axis Values (`#use-chart-range`):
```js
$('#use-chart-range').click(function() {
    if (!lineChart) return;
    let option = lineChart.getOption();
    // Get the current dataZoom range
    let dz = option.dataZoom[0];
    let xAxis = option.xAxis[0];
    // ECharts provides the actual min/max via getModel
    let model = lineChart.getModel();
    let axis = model.getComponent('xAxis', 0).axis;
    let min = axis.scale.getExtent()[0];
    let max = axis.scale.getExtent()[1];
    window.chartEpochMin = min / 1000 - 1;
    window.chartEpochMax = max / 1000 + 1;
    let startFp = document.querySelector('#start-date')._flatpickr;
    let endFp = document.querySelector('#end-date')._flatpickr;
    startFp.setDate(new Date(min), false);
    endFp.setDate(new Date(max), false);
});
```

### Remove zoom button handlers:
Delete the `$('#zoom-reset')`, `$('#zoom-in')`, `$('#zoom-out')` click handlers — ECharts `dataZoom` + `toolbox.restore` handles all of this.

---

## Phase 6: Cleanup

### Files to modify:
| File | Changes |
|---|---|
| `templates/index.html` | Swap CDN scripts, `<canvas>` → `<div>`, remove zoom buttons |
| `static/js/scripts.js` | Rewrite all chart functions, stake system, controls |
| `static/css/styles.css` | Remove `.heatmap-table` styles (no longer needed), keep layout styles |

### Functions to rewrite in `scripts.js`:
1. `updateLineChart()` — line → ECharts line
2. `updatePieChart()` — pie → ECharts pie
3. `updateTopNChart()` — bar → ECharts horizontal bar
4. `updateStackedBarChart()` — stacked bar → ECharts stacked bar
5. `updateErrorRateChart()` — dual-axis line → ECharts dual-axis
6. `updateHeatmap()` — HTML table → ECharts heatmap
7. `updateTreemapChart()` — canvas-drawn → ECharts treemap
8. `updateSyncTimeline()` — bar → ECharts horizontal bar
9. `updateSyncGantt()` — broken Chart.js → ECharts custom series ⭐
10. `addStakeToChart()` — annotation → markLine
11. `removeStakeFromChart()` — annotation → markLine
12. `makeStakeAnnotation()` — remove (replaced by markLine data)
13. Zoom handlers — remove (built-in dataZoom)
14. Scale toggle handler — simplify

### Keep unchanged:
- `getTypeColor()` — works as-is, colors are just strings
- `fetchData()` — data fetching logic stays the same
- `updateTable()` — raw data table is HTML, not a chart
- `updateReplicationHistory()` — HTML table, not a chart
- `clickStartDate()`, `clickProcessId()` — utility functions
- All Flatpickr / filter / tab / checkbox logic

### CSS to remove:
- `.heatmap-table` and related styles (replaced by native ECharts)
- `#pieChart { width: 100% !important; }` (not needed for div)

### CSS to keep:
- `.tabs-full-width`, `.line-chart-container`, `.table-container`, etc.

---

## Execution Order

Recommend doing this in order:
1. **Phase 1** — Swap libraries, canvas→div (app will be broken until Phase 3)
2. **Phase 3I** — Gantt first (the reason we're migrating)
3. **Phase 3A** — Main line chart (most complex, has stakes)
4. **Phase 4** — Stakes system
5. **Phase 3B–3H** — Remaining charts (can be done in any order)
6. **Phase 5** — Controls (scale toggle, use chart range)
7. **Phase 2** — Globals, resize handler
8. **Phase 6** — Cleanup

## Testing Checklist
- [ ] Main line chart renders with time x-axis
- [ ] Line chart drag-to-zoom works (dataZoom)
- [ ] Line chart "Use Chart's X-Axis" button works
- [ ] Scale toggle (linear/log) works
- [ ] Stakes add/remove on line chart and error rate chart
- [ ] Clear All Stakes works
- [ ] Pie chart renders with legend
- [ ] Top-N horizontal bar renders top 15
- [ ] Stacked bar renders by hour
- [ ] Error rate dual-axis renders
- [ ] Heatmap renders with color scale and tooltips
- [ ] Treemap renders with labels and tooltips
- [ ] Sync Timeline bar chart renders
- [ ] **Sync Gantt shows overlapping sessions per PID** ⭐
- [ ] All charts resize on window resize
- [ ] Limit change doesn't break date range (epoch bug fix still works)
- [ ] Reset Filters resets all charts
