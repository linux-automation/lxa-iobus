"use strict";

async function set_nodes(nodes) {
  const rows = document.createDocumentFragment();
  for (const [node_name, node] of Object.entries(nodes)) {
    const tr = document.createElement("tr");

    if (node.locator) {
      tr.classList.add("locator_highlight");
    }

    const a_name = document.createElement("a");
    a_name.style.color = "inherit";
    a_name.style.textDecoration = "none";
    a_name.innerText = node_name;

    if (node.info.update_name) {
      const strong_update = document.createElement("strong");
      strong_update.innerText = " Update";
      strong_update.style.color = "red";

      a_name.appendChild(strong_update);
    }

    const td_name = document.createElement("td");
    td_name.appendChild(a_name);
    tr.appendChild(td_name);

    const td_address = document.createElement("td");
    td_address.innerText = node.info.address;
    tr.appendChild(td_address);

    const td_driver = document.createElement("td");
    td_driver.innerText = node.driver;
    tr.appendChild(td_driver);

    rows.appendChild(tr);
  }

  const tbody = document.getElementById("node-table-tbody");
  tbody.replaceChildren(rows);
}

function keep_status_updated() {
  const es = new EventSource("/api/v2/status?server&nodes");

  es.onmessage = (event) => {
    const message = JSON.parse(event.data);
    set_server_info(message.server);
    set_nodes(message.nodes);
  };
}

keep_status_updated();
