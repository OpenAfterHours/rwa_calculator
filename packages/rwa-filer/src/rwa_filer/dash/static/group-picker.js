const loadChoices = document.getElementById("load-unit-options");
const form = loadChoices.form;
const codes = document.getElementById("group-codes");
const columns = document.getElementById("breakdown-columns");
const statusText = document.getElementById("unit-options-status");
let requestNumber = 0;
let choicesLoaded = false;

function fill(list, values) {
  if (list) list.replaceChildren(...values.map(value => new Option(value, value)));
}

async function refreshChoices() {
  const request = ++requestNumber;
  const data = new FormData(form);
  choicesLoaded = true;
  fill(codes, []);
  statusText.textContent = "Reading choices…";
  try {
    const response = await fetch("/open/breakdown-options", {method: "POST", body: data});
    const options = await response.json();
    if (request !== requestNumber) return;
    if (!response.ok) throw new Error(options.error || "Could not read the file.");
    fill(columns, options.columns);
    fill(codes, options.codes);
    statusText.textContent = options.codes.length
      ? `${options.codes.length} available group codes.`
      : "Choose one breakdown column to see its codes.";
  } catch (error) {
    if (request === requestNumber) statusText.textContent = error.message;
  }
}

loadChoices.addEventListener("click", refreshChoices);
form.addEventListener("change", event => {
  if (["file", "path"].includes(event.target.name)) {
    requestNumber++;
    choicesLoaded = false;
    fill(columns, []);
    fill(codes, []);
    statusText.textContent = "";
  } else if (event.target.name === "breakdown" && choicesLoaded) {
    refreshChoices();
  }
});
