"use strict";

function array_equal(a, b) {
  return a.length === b.length && a.every((val, index) => val === b[index]);
}

async function post_json(url, content) {
  const body = JSON.stringify(content);

  const headers = new Headers();
  headers.append("Content-Type", "application/json");

  await fetch(url, {
    body: body,
    headers: headers,
    method: "POST",
  });
}

function set_server_info(data) {
  data["can_interface_is_up"] = data["can_interface_is_up"] ? "UP" : "DOWN";
  data["can_tx_error"] = data["can_tx_error"] ? "TX_ERROR!" : "";

  const key_elem = [
    ["hostname", "server-info-hostname"],
    ["started", "server-info-server-started"],
    ["can_interface", "server-info-can-interface"],
    ["can_interface_is_up", "server-info-can-interface-state"],
    ["can_tx_error", "server-info-can-tx-error"],
    ["lss_state", "server-info-lss-state"],
  ];

  for (const [key, elem] of key_elem) {
    document.getElementById(elem).innerText = data[key];
  }
}
