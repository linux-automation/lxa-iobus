"use strict";

function keep_isp_console_updated() {
  const es = new EventSource("/api/v2/isp_log");
  const isp_console = document.getElementById("isp-console");

  es.onmessage = (event) => {
    let code = document.createElement("code");
    code.innerText = event.data;
    isp_console.appendChild(code);

    let br = document.createElement("br");
    isp_console.appendChild(br);
    isp_console.scrollTop = isp_console.scrollHeight;
  };
}

keep_isp_console_updated();

function keep_server_info_updated() {
  const es = new EventSource("/api/v2/status?server");

  es.onmessage = (event) => {
    const message = JSON.parse(event.data);
    set_server_info(message.server);
  };
}

keep_server_info_updated();
