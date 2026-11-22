const BAND_COLOUR = {
    light: { reliable: "#2d7d55", moderate: "#b5761f", weak: "#a3453b" },
    dark: { reliable: "#5cb98a", moderate: "#e0a04a", weak: "#d8706a" }
};

const GROWTH_HUE = { light: "#0f6e6e", dark: "#4ab3b3" };
const CHART_INK = { light: "#5a6b7a", dark: "#9aabb8" };
const CHART_GRID = { light: "#e6ecf0", dark: "#32414d" };
const TOOLTIP_BG = { light: "#16202a", dark: "#0b1116" };
const MAP_EDGE = { light: "#8da0ad", dark: "#4e6273" };
const MAP_BLANK = { light: "#eef2f4", dark: "#273440" };

const state = {
    year: 2030,
    selected: null,
    mode: "growth",
    sort: "growth"
};

const forecastCache = {};
const historyCache = {};

let chart = null;
let map = null;
let mapLayer = null;
let geojson = null;


function currentTheme() {
    const override = document.documentElement.dataset.theme;
    if (override) {
        return override;
    }
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function bandColour(band) {
    return BAND_COLOUR[currentTheme()][band];
}

async function getJson(path) {
    const response = await fetch(path);
    if (!response.ok) {
        throw new Error(path + " returned " + response.status);
    }
    return response.json();
}

async function getForecast(year) {
    if (!forecastCache[year]) {
        forecastCache[year] = await getJson("/forecast?year=" + year);
    }
    return forecastCache[year];
}

async function getHistory(district) {
    if (!historyCache[district]) {
        const data = await getJson("/history/" + district);
        historyCache[district] = data.observations;
    }
    return historyCache[district];
}

function growthOf(row) {
    return row.predicted_population / row.baseline;
}

function formatNumber(value) {
    return value.toLocaleString("en-US");
}

function showError(message) {
    const box = document.getElementById("error");
    box.hidden = false;
    box.textContent = message;
}


function buildChart() {
    const canvas = document.getElementById("canvas");

    chart = new Chart(canvas, {
        type: "line",
        data: { labels: [], datasets: [] },
        options: {
            maintainAspectRatio: false,
            animation: { duration: 200 },
            interaction: { mode: "index", intersect: false },
            scales: {
                x: {
                    grid: { display: false },
                    ticks: { maxTicksLimit: 9 }
                },
                y: {
                    grid: {},
                    border: { display: false },
                    ticks: {
                        callback: function (value) {
                            return (value / 1000).toFixed(0) + "k";
                        }
                    }
                }
            },
            plugins: {
                legend: { display: false },
                tooltip: {
                    padding: 10,
                    displayColors: false,
                    callbacks: {
                        label: function (item) {
                            if (item.parsed.y === null) {
                                return null;
                            }
                            return item.dataset.label + ": " + formatNumber(Math.round(item.parsed.y));
                        }
                    }
                }
            }
        }
    });

    applyChartTheme();
}

// Chart.js takes colours as values, so they do not follow the CSS variables
// and have to be reapplied whenever the theme changes.
function applyChartTheme() {
    const theme = currentTheme();

    chart.options.scales.x.ticks.color = CHART_INK[theme];
    chart.options.scales.y.ticks.color = CHART_INK[theme];
    chart.options.scales.y.grid.color = CHART_GRID[theme];
    chart.options.plugins.tooltip.backgroundColor = TOOLTIP_BG[theme];
}

async function drawChart() {
    const district = state.selected;
    const history = await getHistory(district);
    const lastObserved = history[history.length - 1].year;
    const endYear = Math.max(state.year, lastObserved);

    const labels = [];
    for (let year = history[0].year; year <= endYear; year++) {
        labels.push(year);
    }

    const forecastYears = labels.filter(year => year >= lastObserved);
    const packs = await Promise.all(forecastYears.map(getForecast));

    const forecast = {};
    forecastYears.forEach(function (year, index) {
        forecast[year] = packs[index].districts[district];
    });

    const observed = labels.map(function (year) {
        const row = history.find(entry => entry.year === year);
        return row ? row.population : null;
    });

    const central = labels.map(year => forecast[year] ? forecast[year].predicted_population : null);
    const low = labels.map(year => forecast[year] ? forecast[year].range.low : null);
    const high = labels.map(year => forecast[year] ? forecast[year].range.high : null);

    // The line takes the reliability colour so a weak forecast reads as a
    // warning before anyone looks at the caveat below it.
    const band = forecast[endYear].reliability.band;
    const lineColour = bandColour(band);

    chart.data.labels = labels;
    chart.data.datasets = [
        { label: "Lower bound", data: low, borderWidth: 0, pointRadius: 0, fill: false },
        { label: "Upper bound", data: high, borderWidth: 0, pointRadius: 0, backgroundColor: lineColour + "33", fill: "-1" },
        { label: "Observed", data: observed, borderColor: lineColour, borderWidth: 2, pointRadius: 0, tension: 0.25, fill: false },
        { label: "Projected", data: central, borderColor: lineColour, borderWidth: 2, borderDash: [5, 4], pointRadius: 0, tension: 0.25, fill: false }
    ];
    chart.update();

    document.getElementById("chart-title").textContent = district + ": fitted history and projection";
    drawCaveat(forecast[endYear].reliability);
}

function drawCaveat(reliability) {
    const box = document.getElementById("caveat");
    box.hidden = false;
    box.dataset.band = reliability.band;
    document.getElementById("caveat-band").textContent = reliability.band + " data";
    document.getElementById("caveat-note").textContent = reliability.note;
}


function shade(hex, intensity) {
    const red = parseInt(hex.slice(1, 3), 16);
    const green = parseInt(hex.slice(3, 5), 16);
    const blue = parseInt(hex.slice(5, 7), 16);
    const theme = currentTheme();

    // Light mode fades toward white, dark mode toward the panel colour,
    // so a low-growth district stays visible either way.
    const base = theme === "dark" ? 26 : 255;
    const mix = value => Math.round(base + (value - base) * (0.12 + 0.88 * intensity));

    return "rgb(" + mix(red) + "," + mix(green) + "," + mix(blue) + ")";
}

async function drawMap() {
    const pack = await getForecast(state.year);
    const rows = pack.districts;
    const theme = currentTheme();

    const factors = Object.values(rows).map(growthOf);
    const lowest = Math.min(...factors);
    const highest = Math.max(...factors);

    function normalise(factor) {
        if (highest === lowest) {
            return 0.6;
        }
        return (factor - lowest) / (highest - lowest);
    }

    function styleFor(feature) {
        const district = feature.properties.ADM2_EN;
        const row = rows[district];

        if (!row) {
            return { color: MAP_EDGE[theme], weight: 1, fillColor: MAP_BLANK[theme], fillOpacity: 1 };
        }

        let fillColor;
        if (state.mode === "growth") {
            fillColor = shade(GROWTH_HUE[theme], normalise(growthOf(row)));
        } else {
            fillColor = bandColour(row.reliability.band);
        }

        const isSelected = district === state.selected;
        return {
            color: isSelected ? (theme === "dark" ? "#e8eef2" : "#16202a") : MAP_EDGE[theme],
            weight: isSelected ? 2.5 : 1,
            fillColor: fillColor,
            fillOpacity: state.mode === "growth" ? 1 : 0.8
        };
    }

    function bindDistrict(feature, layer) {
        const district = feature.properties.ADM2_EN;
        const row = rows[district];

        if (row) {
            layer.bindTooltip(
                "<b>" + district + "</b><br>" +
                formatNumber(row.predicted_population) + " in " + state.year + "<br>" +
                growthOf(row).toFixed(2) + "× its 2020 size<br>" +
                row.reliability.band + " data",
                { sticky: true }
            );
        }

        layer.on("click", function () {
            state.selected = district;
            refresh();
        });
    }

    if (mapLayer) {
        mapLayer.remove();
    }

    mapLayer = L.geoJSON(geojson, { style: styleFor, onEachFeature: bindDistrict }).addTo(map);
    map.fitBounds(mapLayer.getBounds(), { padding: [10, 10] });

    drawLegend();
}

function drawLegend() {
    const title = document.getElementById("map-title");
    const note = document.getElementById("map-note");
    const legend = document.getElementById("legend");
    const hue = GROWTH_HUE[currentTheme()];

    if (state.mode === "growth") {
        title.textContent = "Projected growth since 2020";
        note.textContent = "Darker shading means faster projected growth against the district's 2020 figure.";
        legend.innerHTML =
            "<span>Slower" +
            "<i style='background:" + shade(hue, 0.12) + "'></i>" +
            "<i style='background:" + shade(hue, 0.5) + "'></i>" +
            "<i style='background:" + shade(hue, 1) + "'></i>" +
            "Faster</span>";
    } else {
        title.textContent = "How far the data can be trusted";
        note.textContent = "Shading shows how closely WorldPop's 2020 estimate matches the 2022 census in each district.";
        legend.innerHTML = ["reliable", "moderate", "weak"].map(function (band) {
            return "<span><i style='background:" + bandColour(band) + "'></i>" + band + "</span>";
        }).join("");
    }
}


async function drawList() {
    const pack = await getForecast(state.year);
    const rows = pack.districts;
    const names = Object.keys(rows);

    if (state.sort === "growth") {
        names.sort((a, b) => growthOf(rows[b]) - growthOf(rows[a]));
    } else if (state.sort === "size") {
        names.sort((a, b) => rows[b].predicted_population - rows[a].predicted_population);
    } else {
        names.sort();
    }

    const list = document.getElementById("list");

    list.innerHTML = names.map(function (district) {
        const row = rows[district];
        return "<button type='button' value='" + district + "' aria-pressed='" + (district === state.selected) + "'>" +
            "<span class='dot " + row.reliability.band + "'></span>" +
            "<span>" + district + "<span class='mult'>" + growthOf(row).toFixed(2) + "×</span></span>" +
            "<span class='num'>" + formatNumber(row.predicted_population) + "</span>" +
            "</button>";
    }).join("");

    list.querySelectorAll("button").forEach(function (button) {
        button.onclick = function () {
            state.selected = button.value;
            refresh();
        };
    });
}


async function refresh() {
    document.getElementById("export").href = "/export?year=" + state.year;


    try {
        await drawList();
        await drawChart();
        await drawMap();
    } catch (error) {
        showError(error.message);
    }
}

function wireToggle(containerId, stateKey, onChange) {
    const container = document.getElementById(containerId);

    container.querySelectorAll("button").forEach(function (button) {
        button.onclick = function () {
            state[stateKey] = button.value;
            container.querySelectorAll("button").forEach(function (other) {
                other.setAttribute("aria-pressed", other === button);
            });
            onChange().catch(error => showError(error.message));
        };
    });
}

function wireTheme() {
    const button = document.getElementById("theme");

    function label() {
        button.textContent = currentTheme() === "dark" ? "Light" : "Dark";
    }

    button.onclick = function () {
        document.documentElement.dataset.theme = currentTheme() === "dark" ? "light" : "dark";
        label();
        applyChartTheme();
        refresh();
    };

    // Follow the system until the user overrides it.
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", function () {
        if (!document.documentElement.dataset.theme) {
            label();
            applyChartTheme();
            refresh();
        }
    });

    label();
}

async function init() {
    try {
        const districts = (await getJson("/districts")).districts;
        state.selected = districts.includes("Gasabo") ? "Gasabo" : districts[0];

        geojson = await getJson("/geojson");

        map = L.map("map", { scrollWheelZoom: false, attributionControl: false, zoomControl: false });
        L.control.zoom({ position: "topright" }).addTo(map);

        buildChart();
        wireTheme();

        const slider = document.getElementById("year");
        slider.oninput = function () {
            state.year = Number(slider.value);
            document.getElementById("yearout").textContent = slider.value;
        };
        slider.onchange = refresh;

        wireToggle("mode", "mode", drawMap);
        wireToggle("sort", "sort", drawList);

        await refresh();
    } catch (error) {
        showError("Could not load data from the API — " + error.message + ". Is the server running?");
    }
}

init();
