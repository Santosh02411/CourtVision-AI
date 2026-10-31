import { stateEmpty } from "../ui/components.js";
export default function render({ root }) { root.innerHTML = `<div class="card">${stateEmpty("Page not found", "That page doesn't exist. Use the navigation or press Ctrl K to search.", "search")}</div>`; }
