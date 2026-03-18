let lineChart, pieChart, topNChart, errorRateChart, stackedBarChart, treemapChart, syncTimelineChart, syncGanttChart, heatmapChart;
let lineChartData = null;
let pieChartData = null;
let stakes = {};
let stakeColorIndex = 0;
const stakeColors = [
    '#e6194b', '#3cb44b', '#4363d8', '#f58231', '#911eb4',
    '#42d4f4', '#f032e6', '#bfef45', '#fabed4', '#469990'
];

// Persist stakes to Couchbase cache bucket
function saveStakes() {
    $.ajax({
        url: '/save_stakes',
        type: 'POST',
        contentType: 'application/json',
        data: JSON.stringify(stakes)
    });
}

$(document).ready(function() {
    // Load persisted stakes from Couchbase
    $.get('/get_stakes', function(resp) {
        if (resp.status === 'success' && resp.data && Object.keys(resp.data).length > 0) {
            stakes = resp.data;
            stakeColorIndex = Object.keys(stakes).length;
            updateStakesPanel();
        }
    });

    flatpickr("#start-date", {
        enableTime: true,
        enableSeconds: true,
        dateFormat: "Y-m-d H:i:S",
        time_24hr: true,
        allowInput: true,
        minuteIncrement: 1,
        secondIncrement: 1,
        onChange: function() { window.chartEpochMin = null; window.chartEpochMax = null; }
    });

    flatpickr("#end-date", {
        enableTime: true,
        enableSeconds: true,
        dateFormat: "Y-m-d H:i:S",
        time_24hr: true,
        allowInput: true,
        minuteIncrement: 1,
        secondIncrement: 1,
        onChange: function() { window.chartEpochMin = null; window.chartEpochMax = null; }
    });

    $('#select-all').click(function(e) {
        e.preventDefault();
        $('#type-select option').prop('selected', true);
    });

    $('#unselect-all').click(function(e) {
        e.preventDefault();
        $('#type-select option').prop('selected', false);
    });

    // Window resize handler for all ECharts instances
    window.addEventListener('resize', function() {
        [lineChart, pieChart, topNChart, errorRateChart, stackedBarChart,
         treemapChart, syncTimelineChart, syncGanttChart, heatmapChart]
            .forEach(c => c && c.resize());
    });

    // Resize ECharts instances when their tab becomes visible
    $(document).on('click', '.addui-Tabs-tab', function() {
        setTimeout(function() {
            [lineChart, pieChart, topNChart, errorRateChart, stackedBarChart,
             treemapChart, syncTimelineChart, syncGanttChart, heatmapChart]
                .forEach(c => c && c.resize());
        }, 50);
    });

    // Fetch types for filters first
    $.get('/get_types', function(types) {
        let select = $('#type-select');
        select.append(`<option value="Error" selected>Error</option>`);
        select.append(`<option value="📌 Stakes" selected>📌 Stakes</option>`);
        types.forEach(function(type) {
            select.append(`<option value="${type}" selected>${type}</option>`);
        });
        console.log("Type select options after population:", $('#type-select').val());

        $.get('/get_date_range', function(dateRange) {
            console.log("Received date range:", dateRange);
            $('#start-date').val(dateRange.start_date + ' 00:00:00');
            $('#end-date').val(dateRange.end_date + ' 23:59:58');
            fetchData();
        }).fail(function() {
            console.error("Failed to fetch date range, using fallback.");
            $('#start-date').val('2023-01-01 00:00:00');
            $('#end-date').val('2023-12-31 23:59:58');
            fetchData();
        });
    }).fail(function() {
        console.error("Failed to fetch types, proceeding with default 'Error' option.");
        let select = $('#type-select');
        select.append(`<option value="Error" selected>Error</option>`);
        select.append(`<option value="📌 Stakes" selected>📌 Stakes</option>`);
        console.log("Type select options after population (fallback):", $('#type-select').val());

        $.get('/get_date_range', function(dateRange) {
            console.log("Received date range:", dateRange);
            $('#start-date').val(dateRange.start_date + ' 00:00:00');
            $('#end-date').val(dateRange.end_date + ' 23:59:58');
            fetchData();
        }).fail(function() {
            console.error("Failed to fetch date range, using fallback.");
            $('#start-date').val('2023-01-01 00:00:00');
            $('#end-date').val('2023-12-31 23:59:58');
            fetchData();
        });
    });

});


    function filterLogReportByDateRange(logReportData, startDate, endDate) {
        if (!startDate || !endDate) return logReportData;
        let startMs = new Date(startDate.replace(' ', 'T')).getTime();
        let endMs = new Date(endDate.replace(' ', 'T')).getTime();
        if (isNaN(startMs) || isNaN(endMs)) return logReportData;

        let filtered = {};
        // Copy non-array properties as-is
        for (let key in logReportData) {
            if (!Array.isArray(logReportData[key])) {
                filtered[key] = logReportData[key];
                continue;
            }
            filtered[key] = logReportData[key].filter(entry => {
                if (!entry.startTime) return false;
                let t = new Date(entry.startTime).getTime();
                return t >= startMs && t <= endMs;
            });
        }
        return filtered;
    }

    function fetchData() {
        let selectedTypes = $('#type-select').val() || [];
        let selectedTypeResult = ($('#type-select').val() || []).length === $('#type-select option').length;
        let startDate = $('#start-date').val();
        let endDate = $('#end-date').val();
        let searchTerm = $('#search-input').val().trim();
        let useSpecificType = $('#type-mode-toggle').is(':checked');
        let groupingMode = $('#grouping-mode-toggle').is(':checked') ? 'by-minute' : 'by-second';
        let errorFilter = selectedTypes.includes('Error');
        let limit = $('#limit-select').val();

        let filters = {
            use_specific_type: useSpecificType,
            grouping_mode: groupingMode,
            error_filter: errorFilter,
            types: selectedTypes,
            allTypeSelected: selectedTypeResult,
            search_term: searchTerm,
            limit: limit
        };
        if (startDate) filters.start_date = startDate;
        if (endDate) filters.end_date = endDate;
        if (window.chartEpochMin && window.chartEpochMax) {
            filters.start_epoch = window.chartEpochMin;
            filters.end_epoch = window.chartEpochMax;
        }

        console.log("fetchData filters:", JSON.stringify(filters, null, 2));

        $.ajax({
            url: '/debug_query',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify(filters),
            success: function(resp) {
                console.log("DEBUG FTS query:", JSON.stringify(resp.fts_query, null, 2));
            }
        });

        $.ajax({
            url: '/get_chart_data',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify(filters),
            success: function(chartData) {
                lineChartData = chartData;
                updateLineChart(chartData.data, errorFilter);
                updateErrorRateChart(chartData.data);
                updateStackedBarChart(chartData.data);
                updateHeatmap(chartData.data);
            },
            error: function() {
                alert('Error fetching line chart data');
            }
        });

        $.ajax({
            url: '/get_pie_data',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({
                start_date: filters.start_date,
                end_date: filters.end_date,
                search_term: searchTerm
            }),
            success: function(pieData) {
                pieChartData = pieData;
                updatePieChart(pieData.data);
                updateTopNChart(pieData.data);
                updateTreemapChart(pieData.data);
            },
            error: function() {
                alert('Error fetching pie chart data');
            }
        });

        $.ajax({
            url: '/get_raw_data',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify(filters),
            success: function(rawData) {
                updateTable(rawData.data, searchTerm);
            },
            error: function() {
                alert('Error fetching raw data');
            }
         });

        $.ajax({
            url: '/get_log_report',
            type: 'GET',
            dataType: 'json',
            success: function(logReportData) {
                // Filter log_report data by current date range
                let filteredReport = filterLogReportByDateRange(logReportData, startDate, endDate);
                updateReplicationHistory(filteredReport);
                updateSyncTimeline(filteredReport);
                updateSyncGantt(filteredReport);
            },
            error: function() {
                alert('Error fetching raw data');
            }
        });
    }

    function updateReplicationHistory(logReportData) {
        let tableBody = document.querySelector('#replication-report-table tbody');
        if (!tableBody) {
            console.error('Table body not found!');
            return;
        }
        tableBody.innerHTML = '';

        const replicationStats = logReportData?.["replicationStats"] || [];
        const sortedStats = [...replicationStats].sort((a, b) => new Date(a.startTime) - new Date(b.startTime));

        var totalDocsProcess = 0;
        var totalDocsReject = 0;
        var totalEndpoint = 0;

        sortedStats.forEach((entry, index) => {
            const docCount = entry.documentsProcessedCount || 0;
            const rejectCount = entry.localWriteRejectionCount || 0;
            const docCountHtml = docCount > 0 ? `<strong style="color: green;">${docCount}</strong>` : docCount;
            const rejectCountHtml = rejectCount > 0 ? `<strong style="color: red;">${rejectCount}</strong>` : rejectCount;
            const endpoint = entry.endpoint ? `<strong style="color: green;">${entry.endpoint}</strong>` : '';

            totalDocsProcess += docCount;
            totalDocsReject += rejectCount;
            totalEndpoint += (entry.endpoint && entry.endpoint.trim() !== '') ? 1 : 0;

            var datepicker = entry.startTime.replace('T', ' ').slice(0, 19);
            tableBody.insertAdjacentHTML('beforeend', `
                <tr>
                    <td>${index + 1}</td>
                    <td > <button class="date-button" onclick="clickStartDate('${datepicker}')">${entry.startTime?.split("T")[1] || ''}</button></td>
                    <td>${entry.replicationProcessId || ''}</td>
                    <td>${docCountHtml}</td>
                    <td>${rejectCountHtml}</td>
                    <td>${endpoint}</td>
                </tr>
            `);
        });

        $("#docProcessHead").html(totalDocsProcess);
        $("#syncWriteRejectHead").html(totalDocsReject);
        $("#endpointHead").html(totalEndpoint);

        let table2Body = document.querySelector('#replicator-table tbody');
        if (!table2Body) {
            console.error('Table body not found!');
            return;
        }

        table2Body.innerHTML = ""
        const replicationStarts = logReportData?.["replicationStarts"] || [];
        const sortedReplicator = [...replicationStarts].sort((a, b) => new Date(a.startTime) - new Date(b.startTime));

        sortedReplicator.forEach((entry, index) => {

            var datepicker2 = entry.startTime.replace('T', ' ').slice(0, 19);

            var more = ""
            if (entry.endpoint.type === "url") {
                more += " AND rawLog:ws:// OR rawLog:wss://"
            }

            if (entry.endpoint.type === "message") {
                more += " AND rawLog:x-msg-conn"
            }

            table2Body.insertAdjacentHTML('beforeend', `
                <tr>
                    <td>${index + 1}</td>
                    <td> <button class="date-button" onclick="clickStartDate('${datepicker2}')">${entry.startTime?.split("T")[1] || ''}</button></td>
                    <td><button class="date-button" onclick="clickProcessId('${entry.processId[0] + more || ''}')">${entry.processId[0] || ''}</button></td>
                    <td>${entry.endpoint.value || ''}</td>
                    <td>${entry.collectionCount}</td>
                </tr>
            `);
        }
    )}

    function clickStartDate(timestamp) {
        $('#start-date').val(timestamp);
    }

function clickProcessId(processId,more="") {
    var processIdFts = "+processId:" + processId.toString() + more;
    $('#search-input').val(processIdFts)
}

// ─── Main Line Chart (ECharts) ───
function updateLineChart(data, errorFilter) {
    if (!data || data.length === 0) {
        console.log("No data to display for line chart");
        return;
    }

    let datasets = {};
    data.forEach(function(item) {
        if (!item.second || !item.type || typeof item.count !== 'number') return;
        let type = item.type;
        if (!datasets[type]) datasets[type] = [];
        datasets[type].push([item.second, item.count]);
    });

    let series = Object.keys(datasets).map(type => {
        let group = type.split(':')[0];
        let specificTypes = Object.keys(datasets).filter(t => t.startsWith(group));
        return {
            name: type,
            type: 'line',
            data: datasets[type].sort((a, b) => a[0].localeCompare(b[0])),
            smooth: 0.4,
            showSymbol: false,
            itemStyle: { color: getTypeColor(type, errorFilter, specificTypes) },
            markLine: { data: [] }
        };
    });

    // Re-apply existing stakes as markLine on the first series (if visible)
    if (series.length > 0 && Object.keys(stakes).length > 0 && stakesVisible()) {
        let markData = [];
        Object.keys(stakes).forEach(docKey => {
            let s = stakes[docKey];
            let label = stakeLabel(s.rawTimestamp);
            markData.push({
                name: label,
                xAxis: s.timestamp,
                lineStyle: { color: s.color, type: 'dashed', width: 2 },
                label: { show: true, formatter: label, color: '#fff',
                         backgroundColor: s.color, padding: [2, 4], borderRadius: 2 },
                _stakeId: docKey
            });
        });
        series[0].markLine = { silent: false, symbol: 'none', data: markData };
    }

    let scaleType = $('#scale-mode-toggle').is(':checked') ? 'log' : 'value';

    if (!lineChart) lineChart = echarts.init(document.getElementById('lineChart'));
    lineChart.setOption({
        tooltip: { trigger: 'axis' },
        legend: { type: 'scroll', top: 0 },
        grid: { left: 60, right: 30, top: 50, bottom: 80 },
        xAxis: { type: 'time', name: 'Time' },
        yAxis: { type: scaleType, name: '# of Logs', min: scaleType === 'log' ? 1 : 0 },
        dataZoom: [
            { type: 'slider', xAxisIndex: 0, bottom: 10 },
            { type: 'inside', xAxisIndex: 0 }
        ],
        toolbox: {
            feature: {
                dataZoom: {
                    yAxisIndex: 'none',
                    brushStyle: {
                        color: 'rgba(255, 255, 0, 0.2)',
                        borderColor: '#888',
                        borderWidth: 1
                    }
                },
                restore: {},
                saveAsImage: {}
            }
        },
        series: series
    }, true);

    // Auto-activate rectangular drag-to-zoom (like Chart.js drag zoom)
    lineChart.dispatchAction({
        type: 'takeGlobalCursor',
        key: 'dataZoomSelect',
        dataZoomSelectActive: true
    });
}

// ─── Pie Chart (ECharts) ───
function updatePieChart(data) {
    if (!data || !Array.isArray(data) || data.length === 0) {
        console.log("No valid data to display for pie chart");
        return;
    }

    if (!pieChart) pieChart = echarts.init(document.getElementById('pieChart'));
    pieChart.setOption({
        tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
        legend: { type: 'scroll', orient: 'vertical', right: 10, top: 20 },
        series: [{
            type: 'pie',
            radius: ['30%', '70%'],
            data: data.map(d => ({
                name: d.type_prefix || 'Unknown',
                value: d.count || 0,
                itemStyle: { color: getTypeColor(d.type_prefix, false, [], true) }
            })),
            emphasis: { itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0,0,0,0.3)' } }
        }]
    }, true);
}

    function getTypeColor(type, errorFilter, specificTypes = [], forPieChart = false) {
        if (!type) return '#A9A9A9';
        if (errorFilter && type === 'Error') {
            return '#000000';
        }

        const colorMap = {
            'Sync': { base: '#1E90FF', shades: ['#1E90FF', '#4AA8FF', '#76C0FF', '#A2D8FF'] },
            'SQL': { base: '#32CD32', shades: ['#32CD32', '#5DE65D', '#88FF88', '#B3FFB3'] },
            'BLIP': { base: '#FF4500', shades: ['#FF4500', '#FF6A33', '#FF8F66', '#FFB499'] },
            'BLIPMessages': { base: '#FF6347', shades: ['#FF6347', '#FF826B', '#FFA18F', '#FFC0B3'] },
            'CBL': { base: '#FFD700', shades: ['#FFD700', '#FFDE33', '#FFE566', '#FFEC99'] },
            'Changes': { base: '#9400D3', shades: ['#9400D3', '#A933E6', '#BE66F9', '#D399FF'] },
            'DB': { base: '#00CED1', shades: ['#00CED1', '#33DCE0', '#66EAEF', '#99F8FE'] },
            'Other': { base: '#A9A9A9', shades: ['#A9A9A9', '#B8B8B8', '#C7C7C7', '#D6D6D6'] },
            'Query': { base: '#228B22', shades: ['#228B22', '#4BA04B', '#74B574', '#9DCA9D'] },
            'WS': { base: '#FF69B4', shades: ['#FF69B4', '#FF88C3', '#FFA7D2', '#FFC6E1'] },
            'Zip': { base: '#8A2BE2', shades: ['#8A2BE2', '#A154EB', '#B87DF4', '#CFA6FD'] },
            'Actor': { base: '#DC143C', shades: ['#DC143C', '#E43F5E', '#EC6A80', '#F495A2'] }
        };

        if (forPieChart) {
            for (let group in colorMap) {
                if (type.startsWith(group)) {
                    return colorMap[group].base;
                }
            }
            return '#A9A9A9';
        }

        let group = 'Other';
        let shadeIndex = 0;

        for (let key in colorMap) {
            if (type.startsWith(key)) {
                group = key;
                shadeIndex = specificTypes.indexOf(type) % colorMap[key].shades.length;
                break;
            }
        }

        return colorMap[group].shades[shadeIndex];
    }

    function updateTable(data, searchTerm) {
        let tableBody = document.querySelector('#data-table tbody');
        tableBody.innerHTML = '';

        console.log('Data received in updateTable:', data);

        if (!searchTerm || searchTerm.trim() === '') {
            data.forEach((row, index) => {
                let errorValue = row.error ? 'True' : '';
                let errorClass = row.error ? 'error-true' : '';
                let timestamp = extractTimestamp(row.rawLog || '');
                let docKey = row.docKey || '';

                tableBody.insertAdjacentHTML('beforeend', `
                <tr id="row-${index}" data-timestamp="${timestamp}" data-doc-key="${docKey}">
                    <td>${index + 1}</td>
                    <td><button class="stake-btn" data-doc-key="${docKey}" data-row-index="${index}" data-timestamp="${timestamp}" style="padding:2px 8px;cursor:pointer;">📍</button></td>
                    <td>${row.type || ''}</td>
                    <td class="${errorClass}">${errorValue}</td>
                    <td>${row.rawLog || ''}</td>
                    <td>${row.processId || ''}</td>
                </tr>
                `);
            });
        } else {
            const operators = /\s+(AND|OR|NOT)\s+/gi;
            let terms = searchTerm.split(operators)
                .filter(term => !['AND', 'OR', 'NOT'].includes(term.trim().toUpperCase()))
                .map(term => term.trim())
                .filter(term => term.length > 0);

            const cleanedTerms = terms.map(term => {
                return term.replace(/^\+?(processId|rawLog|type|dt):/i, '');
            });

            const regexPatterns = cleanedTerms.map(term => {
                term = term.replace(/\^\d+$/, '');
                let pattern = term.replace(/\*/g, '.*');
                pattern = pattern.replace(/[.+?^${}()|[\]\\]/g, '\\$&');
                return new RegExp(pattern, 'gi');
            });

            data.forEach((row, index) => {
                let errorValue = row.error ? 'True' : '';
                let errorClass = row.error ? 'error-true' : '';
                let rawLogContent = row.rawLog || '';
                let timestamp = extractTimestamp(rawLogContent);
                let docKey = row.docKey || '';

                let highlightedRawLog = rawLogContent;
                regexPatterns.forEach(regex => {
                    highlightedRawLog = highlightedRawLog.replace(regex, match =>
                        `<span style="background-color: yellow">${match}</span>`
                    );
                });

                tableBody.insertAdjacentHTML('beforeend', `
                <tr id="row-${index}" data-timestamp="${timestamp}" data-doc-key="${docKey}">
                    <td>${index + 1}</td>
                    <td><button class="stake-btn" data-doc-key="${docKey}" data-row-index="${index}" data-timestamp="${timestamp}" style="padding:2px 8px;cursor:pointer;">📍</button></td>
                    <td>${row.type || ''}</td>
                    <td class="${errorClass}">${errorValue}</td>
                    <td>${highlightedRawLog}</td>
                    <td>${row.processId || ''}</td>
                </tr>
                `);
            });
        }

        document.getElementById('row-count').textContent = `(${data.length} rows)`;

        // Re-mark any rows that match existing stakes
        reapplyStakesToTable();
    }

    function extractTimestamp(rawLog) {
        let match = rawLog.match(/^(\d{2}:\d{2}:\d{2}\.\d+)/);
        if (match) return match[1];
        match = rawLog.match(/^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+)/);
        if (match) return match[1];
        return '';
    }

    // Check if stakes should be visible (selected in type filter)
    function stakesVisible() {
        let selected = $('#type-select').val() || [];
        return selected.includes('📌 Stakes');
    }

    // Update the stakes management panel in the sidebar
    function updateStakesPanel() {
        let tbody = document.querySelector('#stakes-table tbody');
        let emptyMsg = document.getElementById('stakes-empty');
        tbody.innerHTML = '';
        let keys = Object.keys(stakes);
        if (keys.length === 0) {
            emptyMsg.style.display = '';
            return;
        }
        emptyMsg.style.display = 'none';
        keys.forEach(docKey => {
            let s = stakes[docKey];
            let label = stakeLabel(s.rawTimestamp);
            tbody.insertAdjacentHTML('beforeend', `
                <tr class="stake-panel-row" data-doc-key="${docKey}" style="cursor:default;">
                    <td style="width:10px;padding:2px;">
                        <span style="display:inline-block;width:10px;height:10px;border-radius:2px;background:${s.color};"></span>
                    </td>
                    <td style="padding:2px;font-size:11px;font-family:monospace;position:relative;">${label}</td>
                    <td style="padding:2px;text-align:right;">
                        <button class="stake-panel-remove btn btn-ghost btn-xs" data-doc-key="${docKey}" title="Remove stake">✕</button>
                    </td>
                </tr>
            `);
        });
    }

    // Extract "ss.fff" from a timestamp like "12:34:56.789123" for stake labels
    function stakeLabel(timestamp) {
        if (!timestamp) return '?';
        let match = timestamp.match(/(\d{2})\.(\d+)$/);  // last "ss.fractional"
        if (match) return match[1] + '.' + match[2].substring(0, 3);
        match = timestamp.match(/:(\d{2})$/);  // fallback: just seconds
        if (match) return match[1];
        return timestamp.slice(-6);
    }

    // ─── Stakes (ECharts markLine) ───
    function addStakeToChart(chart, stakeId, timeValue, color, timestamp) {
        if (!chart) return;
        let option = chart.getOption();
        if (!option.series || !option.series.length) return;

        let label = stakeLabel(timestamp);
        let markData = (option.series[0].markLine && option.series[0].markLine.data) || [];
        markData.push({
            name: label,
            xAxis: timeValue,
            lineStyle: { color: color, type: 'dashed', width: 2 },
            label: { show: true, formatter: label, color: '#fff',
                     backgroundColor: color, padding: [2, 4], borderRadius: 2 },
            _stakeId: stakeId
        });
        chart.setOption({ series: [{ markLine: { silent: false, symbol: 'none', data: markData } }] });
    }

    function removeStakeFromChart(chart, stakeId) {
        if (!chart) return;
        let option = chart.getOption();
        if (!option.series || !option.series.length) return;

        let markData = ((option.series[0].markLine && option.series[0].markLine.data) || []).filter(d => d._stakeId !== stakeId);
        chart.setOption({ series: [{ markLine: { data: markData } }] });
    }

    // Gantt stake helpers — uses the hidden _stakes series (index 1)
    function addStakeToGantt(chart, stakeId, timeValue, color, timestamp) {
        if (!chart) return;
        let option = chart.getOption();
        if (!option.series || option.series.length < 2) return;
        let label = stakeLabel(timestamp);
        let markData = (option.series[1].markLine && option.series[1].markLine.data) || [];
        markData.push({
            name: label,
            xAxis: timeValue,
            lineStyle: { color: color, type: 'dashed', width: 2 },
            label: { show: true, formatter: label, color: '#fff',
                     backgroundColor: color, padding: [2, 4], borderRadius: 2 },
            _stakeId: stakeId
        });
        chart.setOption({ series: [{}, { markLine: { silent: false, symbol: 'none', data: markData } }] });
    }

    function removeStakeFromGantt(chart, stakeId) {
        if (!chart) return;
        let option = chart.getOption();
        if (!option.series || option.series.length < 2) return;
        let markData = ((option.series[1].markLine && option.series[1].markLine.data) || []).filter(d => d._stakeId !== stakeId);
        chart.setOption({ series: [{}, { markLine: { data: markData } }] });
    }

    function addStake(docKey, timestamp, rowIndex, color) {
        if (!lineChart || !timestamp) return;
        let timeValue = timestamp;
        if (/^\d{2}:\d{2}:\d{2}/.test(timestamp)) {
            let startDate = $('#start-date').val().split(' ')[0] || '2026-01-01';
            timeValue = startDate + ' ' + timestamp;
        }
        stakes[docKey] = { color: color, timestamp: timeValue, rawTimestamp: timestamp, docKey: docKey };
        if (stakesVisible()) {
            addStakeToChart(lineChart, docKey, timeValue, color, timestamp);
            addStakeToChart(errorRateChart, docKey, timeValue, color, timestamp);
            addStakeToGantt(syncGanttChart, docKey, timeValue, color, timestamp);
        }
        updateStakesPanel();
        saveStakes();
    }

    function removeStake(docKey) {
        let stake = stakes[docKey];
        if (stake) {
            let row = document.querySelector(`tr[data-doc-key="${docKey}"]`);
            if (row) {
                row.style.backgroundColor = '';
                let btn = row.querySelector('.stake-btn');
                if (btn) {
                    btn.textContent = '📍';
                    btn.style.backgroundColor = '';
                    btn.style.color = '';
                    btn.style.border = '';
                }
            }
        }
        delete stakes[docKey];
        removeStakeFromChart(lineChart, docKey);
        removeStakeFromChart(errorRateChart, docKey);
        removeStakeFromGantt(syncGanttChart, docKey);
        updateStakesPanel();
        saveStakes();
    }

    // Re-mark table rows that match existing stakes (called after table render)
    function reapplyStakesToTable() {
        Object.keys(stakes).forEach(docKey => {
            let stake = stakes[docKey];
            let row = document.querySelector(`tr[data-doc-key="${docKey}"]`);
            if (row) {
                row.style.backgroundColor = stake.color + '22';
                let btn = row.querySelector('.stake-btn');
                if (btn) {
                    btn.textContent = '❌';
                    btn.style.backgroundColor = stake.color;
                    btn.style.color = '#fff';
                    btn.style.borderRadius = '4px';
                    btn.style.border = 'none';
                }
            }
        });
    }

    $(document).on('click', '.stake-btn', function() {
        let btn = $(this);
        let docKey = btn.data('doc-key');
        let rowIndex = btn.data('row-index');
        let timestamp = btn.data('timestamp');
        if (stakes[docKey]) {
            removeStake(docKey);
        } else {
            let color = stakeColors[stakeColorIndex % stakeColors.length];
            stakeColorIndex++;
            addStake(docKey, timestamp, rowIndex, color);
            let row = document.getElementById('row-' + rowIndex);
            if (row) {
                row.style.backgroundColor = color + '22';
                btn[0].textContent = '❌';
                btn[0].style.backgroundColor = color;
                btn[0].style.color = '#fff';
                btn[0].style.borderRadius = '4px';
                btn[0].style.border = 'none';
            }
        }
    });

    // Remove stake from the sidebar panel
    $(document).on('click', '.stake-panel-remove', function() {
        let docKey = $(this).data('doc-key');
        if (stakes[docKey]) removeStake(docKey);
    });

    // Hover on stake panel row — fetch rawLog from Couchbase
    $(document).on('mouseenter', '.stake-panel-row', function() {
        let row = $(this);
        if (row.find('.stake-tooltip').length) return; // already showing
        let docKey = row.data('doc-key');
        $.get('/get_doc/' + encodeURIComponent(docKey), function(resp) {
            if (resp.status === 'success' && resp.data && resp.data.rawLog) {
                let snippet = resp.data.rawLog.length > 120 ? resp.data.rawLog.substring(0, 120) + '…' : resp.data.rawLog;
                row.find('td:eq(1)').append(
                    `<div class="stake-tooltip" style="position:absolute;z-index:999;background:#333;color:#fff;
                     padding:6px 8px;border-radius:4px;font-size:10px;max-width:300px;word-break:break-all;
                     white-space:normal;margin-top:2px;box-shadow:0 2px 8px rgba(0,0,0,0.3);">${snippet}</div>`
                );
            }
        });
    });
    $(document).on('mouseleave', '.stake-panel-row', function() {
        $(this).find('.stake-tooltip').remove();
    });

    $('#clear-stakes').click(function() {
        Object.keys(stakes).forEach(docKey => removeStake(docKey));
        stakes = {};
        stakeColorIndex = 0;
        updateStakesPanel();
        saveStakes();
    });

    // Apply filters on button click or search enter
    $('#apply-filters').click(fetchData);
$('#search-input').keypress(function(e) {
    if (e.which === 13) {
        e.preventDefault();
        fetchData();
    }
});
$('#reset-filters').click(function() {
    $('#search-input').val('');
    $('#type-mode-toggle').prop('checked', false);
    $('#grouping-mode-toggle').prop('checked', false);
    $('#type-select option').prop('selected', true);
    $('#limit-select').val('500');
    window.chartEpochMin = null;
    window.chartEpochMax = null;
    $.get('/get_date_range', function(dateRange) {
        let startFp = document.querySelector('#start-date')._flatpickr;
        let endFp = document.querySelector('#end-date')._flatpickr;
        startFp.setDate(dateRange.start_date + ' 00:00:00', false);
        endFp.setDate(dateRange.end_date + ' 23:59:58', false);
        fetchData();
    });
});

    // Grouping toggle — re-fetch data when switching seconds ↔ minutes
    $('#grouping-mode-toggle').change(fetchData);

    // Scale toggle — update line chart y-axis without re-fetching
    $('#scale-mode-toggle').change(function() {
        if (lineChart) {
            let type = $(this).is(':checked') ? 'log' : 'value';
            lineChart.setOption({ yAxis: { type: type, min: type === 'log' ? 1 : 0 } });
        }
    });

    // Use Chart's X-Axis Values button
    $('#use-chart-range').click(function() {
        if (!lineChart) return;
        let model = lineChart.getModel();
        let axis = model.getComponent('xAxis', 0).axis;
        let extent = axis.scale.getExtent();
        let min = extent[0];
        let max = extent[1];
        window.chartEpochMin = min / 1000 - 1;
        window.chartEpochMax = max / 1000 + 1;
        let startFp = document.querySelector('#start-date')._flatpickr;
        let endFp = document.querySelector('#end-date')._flatpickr;
        startFp.setDate(new Date(min), false);
        endFp.setDate(new Date(max), false);
    });


        const checkboxes = document.querySelectorAll('.filter-check');

        function filterRows() {
            const table = document.getElementById('replication-report-table');
            const rows = table.getElementsByTagName('tbody')[0].getElementsByTagName('tr');
            const checkedCols = Array.from(checkboxes)
                .filter(cb => cb.checked)
                .map(cb => parseInt(cb.getAttribute('data-col')));

            Array.from(rows).forEach(row => {
                const cells = row.getElementsByTagName('td');
                let shouldHide = false;

                if (checkedCols.length === 0) {
                    row.classList.remove('hidden');
                    return;
                }

                checkedCols.forEach(colIdx => {
                    const cellValue = cells[colIdx].textContent.trim();

                    if (colIdx === 3 || colIdx === 4) {
                        if (cellValue === '') {
                            shouldHide = true;
                        } else {
                            const numValue = parseInt(cellValue);
                            if (numValue === 0) {
                                shouldHide = true;
                            } else if (numValue > 0) {
                                shouldHide = false;
                            } else {
                                shouldHide = true;
                            }
                        }
                    }
                });

                if (shouldHide) {
                    row.classList.add('hidden');
                } else {
                    row.classList.remove('hidden');
                }
            });
        }

        checkboxes.forEach(checkbox => {
            checkbox.addEventListener('change', filterRows);
        });

        filterRows();

// ─── Top-N Horizontal Bar Chart (ECharts) ───
function updateTopNChart(data) {
    if (!data || !Array.isArray(data) || data.length === 0) {
        console.log("No data for Top-N chart");
        return;
    }

    let sorted = [...data]
        .filter(d => d && d.type_prefix && typeof d.count === 'number')
        .sort((a, b) => a.count - b.count)
        .slice(-15);

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

// ─── Error Rate Timeline (ECharts dual axis) ───
function updateErrorRateChart(data) {
    if (!data || !Array.isArray(data) || data.length === 0) {
        console.log("No data for Error Rate chart");
        return;
    }

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

    let option = {
        tooltip: { trigger: 'axis' },
        legend: { top: 0 },
        grid: { left: 60, right: 60, top: 50, bottom: 60 },
        xAxis: { type: 'time', axisLabel: { rotate: 30 } },
        yAxis: [
            { type: 'value', name: 'Error Rate (%)', max: 100,
              axisLabel: { formatter: '{value}%' } },
            { type: 'value', name: 'Count', position: 'right' }
        ],
        series: [
            { name: 'Error Rate %', type: 'line', data: rateData, yAxisIndex: 0,
              areaStyle: { opacity: 0.1 }, itemStyle: { color: '#DC143C' }, smooth: 0.4 },
            { name: 'Total Logs', type: 'line', data: totalData, yAxisIndex: 1,
              lineStyle: { type: 'dashed' }, itemStyle: { color: '#1E90FF' }, smooth: 0.4, showSymbol: false },
            { name: 'Error Count', type: 'line', data: errorData, yAxisIndex: 1,
              itemStyle: { color: '#000' }, smooth: 0.4, showSymbol: false }
        ]
    };

    // Re-apply existing stakes as markLine on the first series (if visible)
    if (Object.keys(stakes).length > 0 && stakesVisible()) {
        let markData = [];
        Object.keys(stakes).forEach(docKey => {
            let s = stakes[docKey];
            let label = stakeLabel(s.rawTimestamp);
            markData.push({
                name: label,
                xAxis: s.timestamp,
                lineStyle: { color: s.color, type: 'dashed', width: 2 },
                label: { show: true, formatter: label, color: '#fff',
                         backgroundColor: s.color, padding: [2, 4], borderRadius: 2 },
                _stakeId: docKey
            });
        });
        option.series[0].markLine = { silent: false, symbol: 'none', data: markData };
    }

    errorRateChart.setOption(option, true);
}

// ─── Heatmap (ECharts native) ───
function updateHeatmap(data) {
    let container = document.getElementById('heatmapContainer');
    if (!container) return;
    if (!data || !Array.isArray(data) || data.length === 0) {
        container.innerHTML = '<p style="padding:20px;text-align:center;color:#888;">No data for heatmap</p>';
        return;
    }

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
    if (sortedDays.length === 0) {
        container.innerHTML = '<p style="padding:20px;text-align:center;color:#888;">No data for heatmap</p>';
        return;
    }

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

    container.innerHTML = '';

    if (heatmapChart) heatmapChart.dispose();
    heatmapChart = echarts.init(container);
    heatmapChart.setOption({
        tooltip: {
            formatter: p => `${sortedDays[p.value[1]]} ${hours[p.value[0]]}:00<br/>Count: <b>${p.value[2]}</b>`
        },
        grid: { left: 100, right: 40, top: 20, bottom: 60 },
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

// ─── Stacked Bar Chart (ECharts) ───
function updateStackedBarChart(data) {
    if (!data || !Array.isArray(data) || data.length === 0) {
        console.log("No data for Stacked Bar chart");
        return;
    }

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

// ─── Treemap Chart (ECharts native) ───
function updateTreemapChart(data) {
    if (!data || !Array.isArray(data) || data.length === 0) {
        console.log("No data for treemap");
        return;
    }

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

// ─── Sync Gantt (ECharts custom series) ───
function updateSyncGantt(logReportData) {
    let container = document.getElementById('syncGanttChart');
    if (!container) return;

    const replicationStarts = logReportData?.["replicationStarts"] || [];
    const replicationStats = logReportData?.["replicationStats"] || [];

    if (replicationStarts.length === 0 && replicationStats.length === 0) {
        if (syncGanttChart) { syncGanttChart.dispose(); syncGanttChart = null; }
        container.innerHTML = '<p style="padding:20px;text-align:center;color:#888;">No sync data available</p>';
        return;
    }

    let sessions = [];
    let sorted = [...replicationStats].sort((a, b) => new Date(a.startTime) - new Date(b.startTime));

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

    if (sessions.length === 0) return;

    let pids = [...new Set(sessions.map(s => s.pid))].sort();
    let pidColors = {};
    let palette = ['#1E90FF','#32CD32','#FFA500','#9400D3','#FF69B4',
                   '#00CED1','#DC143C','#FFD700','#8A2BE2','#008080'];
    pids.forEach((p, i) => { pidColors[p] = palette[i % palette.length]; });

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

    container.innerHTML = '';
    if (syncGanttChart) syncGanttChart.dispose();
    syncGanttChart = echarts.init(container);
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
        grid: { left: 100, right: 40, top: 50, bottom: 70 },
        xAxis: {
            type: 'time',
            min: Math.min(...sessions.map(s => s.start)),
            max: Math.max(...sessions.map(s => s.end)),
            axisLabel: { rotate: 30, formatter: val => new Date(val).toLocaleTimeString() }
        },
        yAxis: { type: 'category', data: pids },
        dataZoom: [
            { type: 'slider', xAxisIndex: 0, bottom: 5 },
            { type: 'inside', xAxisIndex: 0 }
        ],
        series: [
            {
                type: 'custom',
                renderItem: renderGanttItem,
                encode: { x: [1, 2], y: 0 },
                data: ganttData
            },
            {
                // Hidden line series to hold stake markLines
                name: '_stakes',
                type: 'line',
                data: [],
                silent: true,
                showSymbol: false,
                lineStyle: { width: 0 },
                markLine: { data: [] }
            }
        ]
    }, true);

    // Re-apply existing stakes (if visible)
    if (Object.keys(stakes).length > 0 && stakesVisible()) {
        Object.keys(stakes).forEach(docKey => {
            let s = stakes[docKey];
            addStakeToGantt(syncGanttChart, docKey, s.timestamp, s.color, s.rawTimestamp);
        });
    }
}

// ─── Sync Timeline (ECharts horizontal bar) ───
function updateSyncTimeline(logReportData) {
    let container = document.getElementById('syncTimelineChart');
    if (!container) return;

    const replicationStarts = logReportData?.["replicationStarts"] || [];
    const replicationStats = logReportData?.["replicationStats"] || [];

    if (replicationStarts.length === 0 && replicationStats.length === 0) {
        if (syncTimelineChart) { syncTimelineChart.dispose(); syncTimelineChart = null; }
        container.innerHTML = '<p style="padding:20px;text-align:center;color:#888;">No sync data available</p>';
        return;
    }

    let bars = [];
    replicationStats.forEach((entry, i) => {
        if (!entry.startTime) return;
        let start = new Date(entry.startTime);
        let docCount = entry.documentsProcessedCount || 0;
        let rejectCount = entry.localWriteRejectionCount || 0;
        let label = `PID:${entry.replicationProcessId || '?'}`;
        let endTime;
        if (i + 1 < replicationStats.length && replicationStats[i + 1].startTime) {
            endTime = new Date(replicationStats[i + 1].startTime);
        } else {
            endTime = new Date(start.getTime() + 60000);
        }
        bars.push({
            label: label,
            start: start,
            end: endTime,
            docCount: docCount,
            rejectCount: rejectCount,
            hasError: rejectCount > 0
        });
    });

    if (bars.length === 0) return;

    container.innerHTML = '';
    if (syncTimelineChart) syncTimelineChart.dispose();
    syncTimelineChart = echarts.init(container);
    syncTimelineChart.setOption({
        tooltip: {
            trigger: 'axis',
            axisPointer: { type: 'shadow' },
            formatter: function(params) {
                let idx = params[0].dataIndex;
                let b = bars[idx];
                let lines = [`<b>#${idx+1} ${b.label}</b>`];
                params.forEach(p => { lines.push(`${p.seriesName}: ${p.value}`); });
                lines.push(`Start: ${b.start.toLocaleTimeString()}`);
                lines.push(`End: ${b.end.toLocaleTimeString()}`);
                return lines.join('<br/>');
            }
        },
        legend: { top: 0 },
        grid: { left: 120, right: 30, top: 50, bottom: 30 },
        yAxis: { type: 'category', data: bars.map((b, i) => `#${i+1} ${b.label}`) },
        xAxis: { type: 'value', name: 'Value' },
        series: [
            { name: 'Duration (sec)', type: 'bar', data: bars.map(b => Math.round((b.end - b.start) / 1000)),
              itemStyle: { color: function(p) { return bars[p.dataIndex].hasError ? '#DC143C' : '#1E90FF'; } } },
            { name: 'Docs Processed', type: 'bar', data: bars.map(b => b.docCount),
              itemStyle: { color: 'rgba(50,205,50,0.7)' } },
            { name: 'Write Rejections', type: 'bar', data: bars.map(b => b.rejectCount),
              itemStyle: { color: 'rgba(255,69,0,0.7)' } }
        ]
    }, true);
}
