"use strict";

function get_button_active(button) {
  return button.classList.contains("button-success");
}

function set_button_active(button, active) {
  if (get_button_active(button) != active) {
    if (active) {
      button.classList.add("button-success");
    } else {
      button.classList.remove("button-success");
    }
  }
}

function set_locator(node_name, active) {
  const loc = document.getElementById("locator");

  loc.onclick = (_ev) => {
    set_button_active(loc, !get_button_active(loc));
    post_json(`/nodes/${node_name}/toggle-locator/`, {});
  };

  set_button_active(loc, active);
}

var output_buttons = {};

function create_output_buttons(node_name, names) {
  if (!array_equal(names, Object.keys(output_buttons))) {
    output_buttons = {};

    const elems = document.createDocumentFragment();

    const header = document.createElement("h3");
    header.innerText = "Outputs";
    elems.appendChild(header);

    for (const name of names) {
      const button = document.createElement("button");
      button.innerText = name;
      button.classList.add("pure-button");
      button.onclick = (_ev) => {
        set_button_active(button, !get_button_active(button));
        post_json(`/nodes/${node_name}/pins/${name}/`, {
          value: "toggle",
        });
      };

      output_buttons[name] = button;
      elems.appendChild(button);
    }

    const op_div = document.getElementById("outputs");
    op_div.replaceChildren(elems);
  }

  return output_buttons;
}

function set_outputs(node_name, outputs) {
  if (outputs) {
    const output_names = Object.keys(outputs);
    const buttons = create_output_buttons(node_name, output_names);

    for (const name of output_names) {
      set_button_active(buttons[name], outputs[name]);
    }
  }
}

function value_table(header, kv) {
  const elems = document.createDocumentFragment();

  if (kv) {
    const header_elem = document.createElement("h3");
    header_elem.innerText = header;
    elems.appendChild(header_elem);

    const table = document.createElement("table");
    table.classList.add("pure-table");

    for (const [name, value] of Object.entries(kv)) {
      const tr = document.createElement("tr");

      const th = document.createElement("th");
      th.innerText = name;
      tr.appendChild(th);

      const td = document.createElement("td");
      td.innerText = value;
      tr.appendChild(td);

      table.appendChild(tr);
    }

    elems.appendChild(table);
  }

  return elems;
}

function set_inputs(inputs) {
  const ip_div = document.getElementById("inputs");
  ip_div.replaceChildren(value_table("Inputs", inputs));
}

function set_adcs(adcs) {
  const adc_div = document.getElementById("adcs");
  adc_div.replaceChildren(value_table("ADCs", adcs));
}

async function firmware_upgrade(node_name) {
  await post_json(`/nodes/${node_name}/update/`, {});
}

async function set_node(node_name, node) {
  const node_info_table = document.getElementById("node-info");

  function set_table_entry(qs, value) {
    const elems = node_info_table.querySelectorAll(qs);

    for (const elem of elems) {
      if (value) {
        elem.style.removeProperty("display");
      } else {
        elem.style.display = "none";
      }
      elem.querySelector("td").innerText = value;
    }
  }

  set_table_entry(".node-name", node_name);
  set_table_entry(".node-address", node.info.address);
  set_table_entry(".node-serial", node.info.serial_string);
  set_table_entry(".node-driver", node.driver);
  set_table_entry(".node-vendor-name", node.info.vendor_name);
  set_table_entry(".node-device-name", node.info.device_name);
  set_table_entry(".node-hardware-version", node.info.hardware_version);
  set_table_entry(".node-software-version", node.info.software_version);

  const fw_ud_button = document.getElementById("firmware-update-button");

  if (node.info.update_name) {
    fw_ud_button.innerText = `Update to ${node.info.update_name}`;
    fw_ud_button.onclick = (_ev) => firmware_upgrade(node_name);
    fw_ud_button.style.removeProperty("display");
  } else {
    fw_ud_button.style.display = "none";
  }
}

var status_es = null;

function keep_status_updated(node_name) {
  if (status_es !== null) {
    status_es.close();
    status_es = null;
  }

  status_es = new EventSource(`/api/v2/status?server&nodes&pins=${node_name}`);
  status_es.onmessage = (event) => {
    const message = JSON.parse(event.data);
    const node = message.nodes[node_name];
    const pins = message.pins[node_name];

    if (!node || !pins) {
      // The node has likely disconnected.
      // Direct the user back to the node list.
      window.location.href = "/";
    }

    set_server_info(message.server);

    if (node) {
      set_node(node_name, node);
      set_locator(node_name, node.locator);
    }

    if (pins) {
      set_outputs(node_name, pins.result.outputs);
      set_inputs(pins.result.inputs);
      set_adcs(pins.result.adcs);
    }
  };
}

function hash_change() {
  const node_name = window.location.hash.slice(1);
  keep_status_updated(node_name);
}

window.addEventListener("hashchange", hash_change);
hash_change();
