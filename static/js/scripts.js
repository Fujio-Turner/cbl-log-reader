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

    // Function to fetch data from the server
    function fetchData() {
        let selectedTypes = $('#type-select').val() || [];
        let startDate = $('#start-date').val();
        let endDate = $('#end-date').val();
        let searchTerm = $('#search-input').val().trim();
        let useSpecificType = $('input[name="type-mode"]:checked').val() === 'specific';
        let groupingMode = $('input[name="grouping-mode"]:checked').val() || 'by-second';
        let errorFilter = selectedTypes.includes('Error');
        let typeFilters = errorFilter ? [] : selectedTypes.filter(t => t !== 'Error');
    
        let filters = {
            use_specific_type: useSpecificType,
            grouping_mode: groupingMode,
            error_filter: errorFilter,
            types: typeFilters,
            search_term: searchTerm
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
                console.log("Fetched line chart data:", chartData);
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
                console.log("Fetched pie chart data:", pieData);
                pieChartData = pieData;
                updatePieChart(pieData);
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
                console.log("Fetched raw data:", rawData);
                updateTable(rawData, searchTerm);
            },
            error: function() {
                alert('Error fetching raw data');
            }
    });





    }

    // Function to update the line chart
    function updateLineChart(data, errorFilter) {
        if (!data) {
            console.log("No data to display for line chart");
            return;
        }

        // Log the raw data to inspect its structure
        console.log("Raw data received:", data);

        // Group data by type
        let datasets = {};
        data.forEach(function(item) {
            // Ensure the item has the expected fields
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

        // Create chart datasets with consistent colors
        let chartDatasets = [];
        for (let type in datasets) {
            datasets[type].sort((a, b) => moment(a.x).diff(moment(b.x)));
            // Get all types in the same group for shade calculation
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

        // Extract y-axis values for debugging
        let yValues = chartDatasets.flatMap(dataset => dataset.data.map(point => point.y)).filter(y => typeof y === 'number');
        console.log("Y-axis values from new data:", yValues);

        let scaleType = $('input[name="scale-mode"]:checked').val();
        console.log("Updating chart with scale type:", scaleType);

        if (lineChart) {
            // Log the current chart state before update
            console.log("Current chart datasets before update:", lineChart.data.datasets);
            console.log("Current y-axis scale before update:", lineChart.scales['y']);
            console.log("Current y-axis range before update:", {
                min: lineChart.scales['y'].min,
                max: lineChart.scales['y'].max
            });

            // Update the chart with new data
            lineChart.data.datasets = chartDatasets;
            lineChart.options.scales.y.type = scaleType;
            lineChart.options.scales.y.ticks.min = yValues.length ? Math.min(...yValues) : 0;
            lineChart.options.scales.y.ticks.max = yValues.length ? Math.max(...yValues) : 1;
            lineChart.options.scales.y.ticks.stepSize = yValues.length ? Math.ceil((Math.max(...yValues) - Math.min(...yValues)) / 10) : 1;

            // Force a full redraw
            lineChart.update('none');
            console.log("Chart updated with new datasets:", lineChart.data.datasets);
        } else {
            // Create a new chart instance
            let ctx = document.getElementById('lineChart').getContext('2d');
            console.log("Canvas dimensions before clear:", {
                width: ctx.canvas.width,
                height: ctx.canvas.height
            });
            ctx.clearRect(0, 0, ctx.canvas.width, ctx.canvas.height);
            console.log("Canvas cleared");

            lineChart = new Chart(ctx, {
                type: 'line',
                data: { datasets: chartDatasets
                        
                 },
                options: {
                    tension: 0.3, // This makes the line smooth and curvy
                    fill: false, // Optional: prevents filling under the line
                    responsive: true, // Make the chart responsive
                    maintainAspectRatio: false, // Allow the chart to stretch to fit the container
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
                            title: {
                                display: true,
                                text: 'Error Count'
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
                        }
                    }
                }
            });
            console.log("New chart created with datasets:", lineChart.data.datasets);
        }

        // Log the chart state after update
        console.log("Y-axis scale after update:", lineChart.scales['y']);
        console.log("Y-axis range after update:", {
            min: lineChart.scales['y'].min,
            max: lineChart.scales['y'].max
        });
        console.log("Canvas dimensions after chart update:", {
            width: document.getElementById('lineChart').width,
            height: document.getElementById('lineChart').height
        });
    }

    

    // Function to update the pie chart
    function updatePieChart(data) {
        if (!data) {
            console.log("No data to display for pie chart");
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

        let labels = data.map(item => item.type_prefix);
        let counts = data.map(item => item.count);
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
                responsive: true, // Make the pie chart responsive
                maintainAspectRatio: false, // Allow the pie chart to stretch to fit the container
                plugins: {
                    legend: {
                        position: 'right'
                    }
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

    function updateTable(data) {
        let tableBody = document.querySelector('#data-table tbody');
        tableBody.innerHTML = ''; // Clear existing rows (resets the table)
      
        data.forEach((row, index) => {
          let errorValue = row.error ? 'True' : '';
          let errorClass = row.error ? 'error-true' : '';
      
          tableBody.innerHTML += `
            <tr>
              <td>${index + 1}</td>
              <td>${row.type || ''}</td>
              <td class="${errorClass}">${errorValue}</td>
              <td>${row.rawLog || ''}</td>
            </tr>
          `;
        });
      
        // Update the row count
        document.getElementById('row-count').textContent = `(${data.length} rows)`;
      }

    // Apply filters on button click, radio change, date change, or search input change
    $('#apply-filters').click(fetchData);
    $('input[name="type-mode"]').change(fetchData);
    $('input[name="grouping-mode"]').change(fetchData);
    $("#start-date, #end-date").on("change", fetchData);
    $("#search-input").on("input", fetchData);

    // Update chart scale without re-fetching data
    $('input[name="scale-mode"]').change(function() {
        if (lineChartData) {
            updateLineChart(lineChartData, $('#type-select').val().includes('Error'));
        }
    });


    

});