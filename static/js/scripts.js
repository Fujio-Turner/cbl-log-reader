let lineChart, pieChart;
let lineChartData = null; // Store line chart data
let pieChartData = null; // Store pie chart data

$(document).ready(function() {
    // Initialize Flatpickr for date and time picking using native syntax
    flatpickr("#start-date", {
        enableTime: true,
        dateFormat: "Y-m-d H:i:S",
        time_24hr: true,
        minuteIncrement: 1,
        secondIncrement: 1
    });

    flatpickr("#end-date", {
        enableTime: true,
        dateFormat: "Y-m-d H:i:S",
        time_24hr: true,
        minuteIncrement: 1,
        secondIncrement: 1
    });

        // Select All button click handler
        $('#select-all').click(function(e) {
            e.preventDefault();
            $('#type-select option').prop('selected', true);
        });
    
        // Unselect All button click handler
        $('#unselect-all').click(function(e) {
            e.preventDefault();
            $('#type-select option').prop('selected', false);
        });


    // Fetch types for filters first
    $.get('/get_types', function(types) {
        let select = $('#type-select');
        // Add "Error" as a default option
        select.append(
            `<option value="Error" selected>Error</option>`
        );
        // Add the rest of the types from the server
        types.forEach(function(type) {
            select.append(
                `<option value="${type}" selected>${type}</option>`
            );
        });
        console.log("Type select options after population:", $('#type-select').val());

        // Now fetch the date range and call fetchData
        $.get('/get_date_range', function(dateRange) {
            console.log("Received date range:", dateRange);
            $('#start-date').val(dateRange.start_date + ' 00:00:00');
            $('#end-date').val(dateRange.end_date + ' 23:59:58');
            fetchData(); // Fetch data after setting defaults
        }).fail(function() {
            console.error("Failed to fetch date range, using fallback.");
            $('#start-date').val('2023-01-01 00:00:00');
            $('#end-date').val('2023-12-31 23:59:58');
            fetchData();
        });
    }).fail(function() {
        console.error("Failed to fetch types, proceeding with default 'Error' option.");
        let select = $('#type-select');
        select.append(
            `<option value="Error" selected>Error</option>`
        );
        console.log("Type select options after population (fallback):", $('#type-select').val());

        // Proceed to fetch date range even if types fail
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


    // Function to fetch data from the server
    function fetchData() {
        // Get the selected values (returns array or empty array if nothing selected)
        let selectedTypes = $('#type-select').val() || [];
        let selectedTypeResult = ($('#type-select').val() || []).length === $('#type-select option').length;
        let startDate = $('#start-date').val();
        let endDate = $('#end-date').val();
        let searchTerm = $('#search-input').val().trim();
        let useSpecificType = $('input[name="type-mode"]:checked').val() === 'specific';
        let groupingMode = $('input[name="grouping-mode"]:checked').val() || 'by-second';
        let errorFilter = selectedTypes.includes('Error');
        //let typeFilters = errorFilter ? [] : selectedTypes.filter(t => t !== 'Error');
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

        // Fetch aggregated data for the line chart
        $.ajax({
            url: '/get_chart_data',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify(filters),
            success: function(chartData) {
                lineChartData = chartData;
                updateLineChart(chartData, errorFilter);
            },
            error: function() {
                alert('Error fetching line chart data');
            }
        });

        // Fetch data for the pie chart
        $.ajax({
            url: '/get_pie_data',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ 
                start_date: filters.start_date, 
                end_date: filters.end_date,
                search_term: searchTerm // Include the search term in the pie chart request
            }),
            success: function(pieData) {
                pieChartData = pieData;
                updatePieChart(pieData.data);
            },
            error: function() {
                alert('Error fetching pie chart data');
            }
        });

        // Fetch raw data for the table
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



        // Fetch log_report Doc
        $.ajax({
            url: '/get_log_report',
            type: 'GET',
            dataType: 'json',
            success: function(logReportData) {
                updateReplicationHistory(logReportData);
            },
            error: function() {
                alert('Error fetching raw data');
            }
        });


    }

    function updateReplicationHistory(logReportData) {
        // Target the table body
        let tableBody = document.querySelector('#replication-report-table tbody');
        if (!tableBody) {
            console.error('Table body not found!');
            return;
        }
        tableBody.innerHTML = ''; // Clear existing rows
      
        // Ensure replicationStats exists and is an array
        const replicationStats = logReportData?.["replicationStats"] || [];
      
        // Sort by startTime (optional, remove if not needed)
        const sortedStats = [...replicationStats].sort((a, b) => new Date(a.startTime) - new Date(b.startTime));
      
        var totalDocsProcess = 0;
        var totalDocsReject = 0;
        var totalEndpoint = 0;  // This will count valid endpoints
      
        sortedStats.forEach((entry, index) => {
            // Format documentsProcessedCount and localWriteRejectionCount
            const docCount = entry.documentsProcessedCount || 0;
            const rejectCount = entry.localWriteRejectionCount || 0;
            const docCountHtml = docCount > 0 ? `<strong style="color: green;">${docCount}</strong>` : docCount;
            const rejectCountHtml = rejectCount > 0 ? `<strong style="color: red;">${rejectCount}</strong>` : rejectCount;
            
            // Check if endpoint exists first, then apply formatting
            const endpoint = entry.endpoint ? `<strong style="color: green;">${entry.endpoint}</strong>` : '';
            
            // Increment counters
            totalDocsProcess += docCount;
            totalDocsReject += rejectCount;
            // Increment totalEndpoint only if endpoint exists and is not empty
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

        // Replicator the table body
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
            // Check if endpoint exists first, then apply formatting

            var more = ""
            if (entry.endpoint.type === "url") {
                more += " AND ws:// OR wss://"
            }

            if (entry.endpoint.type === "message") {
                more += " AND x-msg-conn"
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
    var processIdFts = "+processId:" + processId.toString() + more;  // Fixed toString() capitalization and concatenation
    $('#search-input').val(processIdFts)
}

function updateLineChart(data, errorFilter) {
    if (!data) {
        console.log("No data to display for line chart");
        return;
    }

    console.log("Raw data received:", data);

    // Group data by type
    let datasets = {};
    data.forEach(function(item) {
        if (!item.second || !item.type || typeof item.count !== 'number') {
            console.warn("Skipping invalid data point:", item);
            return;
        }
        let type = item.type;
        if (!datasets[type]) {
            datasets[type] = [];
        }
        datasets[type].push({ x: item.second, y: item.count });
    });

    let chartDatasets = [];
    for (let type in datasets) {
        datasets[type].sort((a, b) => moment(a.x).diff(moment(b.x)));
        let group = type.split(':')[0];
        let specificTypes = Object.keys(datasets).filter(t => t.startsWith(group));
        let borderColor = getTypeColor(type, errorFilter, specificTypes);
        chartDatasets.push({
            label: type,
            data: datasets[type],
            borderColor: borderColor,
            fill: false
        });
    }

    console.log("New chart datasets:", chartDatasets);

    let yValues = chartDatasets.flatMap(dataset => dataset.data.map(point => point.y)).filter(y => typeof y === 'number');
    console.log("Y-axis values from new data:", yValues);

    let scaleType = $('input[name="scale-mode"]:checked').val();
    console.log("Updating chart with scale type:", scaleType);

    if (lineChart) {
        lineChart.data.datasets = chartDatasets;
        lineChart.options.scales.y.type = scaleType;
        lineChart.options.scales.y.min = 0; 
        lineChart.update('none');
        console.log("Chart updated with new datasets:", lineChart.data.datasets);
    } else {
        let ctx = document.getElementById('lineChart').getContext('2d');
        ctx.clearRect(0, 0, ctx.canvas.width, ctx.canvas.height);

        lineChart = new Chart(ctx, {
            type: 'line',
            data: { datasets: chartDatasets },
            options: {
                tension: 0.1,
                fill: false,
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    x: {
                        type: 'time',
                        title: {
                            display: true,
                            text: 'Time'
                        }
                    },
                    y: {
                        type: scaleType,
                        beginAtZero: true,
                        min:0,
                        title: {
                            display: true,
                            text: '# of Logs of a Type'
                        },
                        ticks: {
                            min: yValues.length ? Math.min(...yValues) : 0,
                            max: yValues.length ? Math.max(...yValues) : 1,
                            stepSize: yValues.length ? Math.ceil((Math.max(...yValues) - Math.min(...yValues)) / 10) : 1,
                            callback: function(value) {
                                return value;
                            }
                        }
                    }
                },
                plugins: {
                    legend: {
                        display: true,
                        position: 'top'
                    },
                    zoom: {
                        pan: {
                            enabled: true, // Enable panning
                            mode: 'xy', // Allow panning in both x and y directions
                        },
                        zoom: {
                            wheel: {
                                enabled: true, // Enable zooming with mouse wheel
                            },
                            pinch: {
                                enabled: true, // Enable zooming with pinch gestures
                            },
                            drag: {
                                enabled: true, // Enable rectangular drag-to-zoom
                                backgroundColor: 'rgba(0, 0, 255, 0.3)', // Light blue fill for the zoom box
                                borderColor: 'rgba(0, 0, 255, 1)', // Blue border for the zoom box
                                borderWidth: 1
                            },
                            mode: 'xy', // Zoom in both x and y directions
                        }
                    }
                }
            }
        });
        console.log("New chart created with datasets:", lineChart.data.datasets);
    }

    // Add reset button event listener (only once when chart is created)
    if (!lineChart.resetListenerAdded) {
        $('#zoom-reset').click(function() {
            if (lineChart) {
                lineChart.resetZoom(); // Reset the zoom and pan to the initial state
                console.log("Zoom reset triggered");
            }
        });
        lineChart.resetListenerAdded = true; // Flag to prevent multiple listeners
    }
}

    
    // Function to update the pie chart
// Function to update the pie chart
function updatePieChart(data) {
    if (!data || !Array.isArray(data) || data.length === 0) {
        console.log("No valid data to display for pie chart");
        return;
    }

    let ctx = document.getElementById('pieChart').getContext('2d');
    // Set canvas dimensions for high-DPI displays
    const canvas = document.getElementById('pieChart');
    const dpr = window.devicePixelRatio || 1;
    canvas.width = canvas.clientWidth * dpr;
    canvas.height = canvas.clientHeight * dpr;
    ctx.scale(dpr, dpr);

    ctx.clearRect(0, 0, ctx.canvas.width, ctx.canvas.height);

    if (pieChart) {
        pieChart.destroy();
        pieChart = null;
    }

    // Filter and map data with fallback values
    let labels = data.map(item => item && item.type_prefix ? item.type_prefix : 'Unknown');
    let counts = data.map(item => item && item.count !== undefined ? item.count : 0);
    let backgroundColors = labels.map(label => getTypeColor(label, false, [], true));

    pieChart = new Chart(ctx, {
        type: 'pie',
        data: {
            labels: labels,
            datasets: [{
                data: counts,
                backgroundColor: backgroundColors
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'right'
                }
            },
            title: {
                display: true,
                text: 'Type Distribution'
            }
        }
    });
}

    // Helper function to assign consistent colors based on type
    function getTypeColor(type, errorFilter, specificTypes = [], forPieChart = false) {
        // If the type is "Error" and errorFilter is true, always use black
        if (errorFilter && type === 'Error') {
            return '#000000';
        }

        // Define base colors for each type group
        const colorMap = {
            'Sync': { base: '#1E90FF', shades: ['#1E90FF', '#4AA8FF', '#76C0FF', '#A2D8FF'] }, // DodgerBlue shades
            'SQL': { base: '#32CD32', shades: ['#32CD32', '#5DE65D', '#88FF88', '#B3FFB3'] }, // LimeGreen shades
            'BLIP': { base: '#FF4500', shades: ['#FF4500', '#FF6A33', '#FF8F66', '#FFB499'] }, // OrangeRed shades
            'BLIPMessages': { base: '#FF6347', shades: ['#FF6347', '#FF826B', '#FFA18F', '#FFC0B3'] }, // Tomato shades
            'CBL': { base: '#FFD700', shades: ['#FFD700', '#FFDE33', '#FFE566', '#FFEC99'] }, // Gold shades
            'Changes': { base: '#9400D3', shades: ['#9400D3', '#A933E6', '#BE66F9', '#D399FF'] }, // DarkViolet shades
            'DB': { base: '#00CED1', shades: ['#00CED1', '#33DCE0', '#66EAEF', '#99F8FE'] }, // DarkTurquoise shades
            'Other': { base: '#A9A9A9', shades: ['#A9A9A9', '#B8B8B8', '#C7C7C7', '#D6D6D6'] }, // DarkGray shades
            'Query': { base: '#228B22', shades: ['#228B22', '#4BA04B', '#74B574', '#9DCA9D'] }, // ForestGreen shades
            'WS': { base: '#FF69B4', shades: ['#FF69B4', '#FF88C3', '#FFA7D2', '#FFC6E1'] }, // HotPink shades
            'Zip': { base: '#8A2BE2', shades: ['#8A2BE2', '#A154EB', '#B87DF4', '#CFA6FD'] }, // BlueViolet shades
            'Actor': { base: '#DC143C', shades: ['#DC143C', '#E43F5E', '#EC6A80', '#F495A2'] } // Crimson shades
        };

        // For pie chart, use the base color
        if (forPieChart) {
            for (let group in colorMap) {
                if (type.startsWith(group)) {
                    return colorMap[group].base;
                }
            }
            return '#A9A9A9'; // Default to DarkGray for unknown types
        }

        // For line chart, assign shades based on the specific type
        let group = 'Other';
        let shadeIndex = 0;

        for (let key in colorMap) {
            if (type.startsWith(key)) {
                group = key;
                // Calculate shade index based on the specific type (e.g., Sync:Rejection, Sync:Start)
                shadeIndex = specificTypes.indexOf(type) % colorMap[key].shades.length;
                break;
            }
        }

        return colorMap[group].shades[shadeIndex];
    }

    function updateTable(data, searchTerm) {
        let tableBody = document.querySelector('#data-table tbody');
        tableBody.innerHTML = ''; // Clear existing rows (resets the table)

        console.log('Data received in updateTable:', data);
        
        if (!searchTerm || searchTerm.trim() === '') {
            // No search term, display as is
            data.forEach((row, index) => {
                let errorValue = row.error ? 'True' : '';
                let errorClass = row.error ? 'error-true' : '';
        
                tableBody.insertAdjacentHTML('beforeend', `
                <tr>
                    <td>${index + 1}</td>
                    <td>${row.type || ''}</td>
                    <td class="${errorClass}">${errorValue}</td>
                    <td>${row.rawLog || ''}</td>
                    <td>${row.processId || ''}</td>
                </tr>
                `);
            });
        } else {
            // Split the search term by operators and clean up
            const operators = /\s+(AND|OR|NOT)\s+/gi;
            let terms = searchTerm.split(operators)
                .filter(term => !['AND', 'OR', 'NOT'].includes(term.trim().toUpperCase()))
                .map(term => term.trim())
                .filter(term => term.length > 0);
        
            // Process terms to remove prefixes like +processId: or +processed:
            const cleanedTerms = terms.map(term => {
                // Remove +processId: or +processed: followed by value
                return term.replace(/^\+?(processId|rawLog|type|dt):/i, '');
            });
        
            // Create regex patterns for each cleaned term
            const regexPatterns = cleanedTerms.map(term => {
                // Remove boost (^n)
                term = term.replace(/\^\d+$/, '');
                
                // Convert wildcard * to regex .*
                let pattern = term.replace(/\*/g, '.*');
                
                // Escape special regex characters (except *)
                pattern = pattern.replace(/[.+?^${}()|[\]\\]/g, '\\$&');
                
                return new RegExp(pattern, 'gi');
            });
        
            data.forEach((row, index) => {
                let errorValue = row.error ? 'True' : '';
                let errorClass = row.error ? 'error-true' : '';
                let rawLogContent = row.rawLog || '';
                
                // Apply highlighting for each term
                let highlightedRawLog = rawLogContent;
                regexPatterns.forEach(regex => {
                    highlightedRawLog = highlightedRawLog.replace(regex, match => 
                        `<span style="background-color: yellow">${match}</span>`
                    );
                });
        
                tableBody.insertAdjacentHTML('beforeend', `
                <tr>
                    <td>${index + 1}</td>
                    <td>${row.type || ''}</td>
                    <td class="${errorClass}">${errorValue}</td>
                    <td>${highlightedRawLog}</td>
                    <td>${row.processId || ''}</td>
                </tr>
                `);
            });
        }
        
        // Update the row count
        document.getElementById('row-count').textContent = `(${data.length} rows)`;
    }




    // Apply filters on button click, radio change, date change, or search input change
    $('#apply-filters').click(fetchData);
   // $('input[name="type-mode"]').change(fetchData);
    //$('input[name="grouping-mode"]').change(fetchData);
    //$("#start-date, #end-date").on("change", fetchData);
    //$("#search-input").on("input", fetchData);

    // Update chart scale without re-fetching data
    $('input[name="scale-mode"]').change(function() {
        if (lineChartData) {
            updateLineChart(lineChartData, $('#type-select').val().includes('Error'));
        }
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

                // If no checkboxes are checked, show all rows
                if (checkedCols.length === 0) {
                    row.classList.remove('hidden');
                    return;
                }

                checkedCols.forEach(colIdx => {
                    const cellValue = cells[colIdx].textContent.trim();
                    
                    if (colIdx === 3 || colIdx === 4) { // Columns 4 and 5 (integer columns)
                        if (cellValue === '') {
                            shouldHide = true; // Empty cells should hide
                        } else {
                            const numValue = parseInt(cellValue);
                            if (numValue === 0) {
                                shouldHide = true; // 0 should hide
                            } else if (numValue > 0) {
                                shouldHide = false; // > 0 should show (but won't override other conditions)
                            } else {
                                shouldHide = true; // < 0 should hide
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

        // Add event listeners to all checkboxes
        checkboxes.forEach(checkbox => {
            checkbox.addEventListener('change', filterRows);
        });

        // Initial filter
        filterRows();
