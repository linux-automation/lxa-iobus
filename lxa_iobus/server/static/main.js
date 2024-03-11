// helper functions -----------------------------------------------------------
function toggle_locator(node_address) {
  $.post("/nodes/" + node_address + "/toggle-locator/");

  update_pin_info();
}

function toggle_pin(node_address, pin_name) {
  $.post("/nodes/" + node_address + "/pins/" + pin_name + "/", {
    value: "toggle",
  });

  update_pin_info();
}

function get_firmware_files() {
  $.getJSON("/firmware/").done(function (data) {
    ractive.set("firmware", data);
  });
}

function flash_firmware(node_address, firmware) {
  $.post("/nodes/" + node_address + "/flash-firmware/" + firmware, {});
  ractive.set("template", "isp");
}

function update_node(node_address, firmware) {
  $.post("/nodes/" + node_address + "/update/", {});
  ractive.set("template", "isp");
}

function delete_firmware(filename) {
  $.post("/firmware/delete/" + filename, {}).done(function () {
    get_firmware_files();
  });
}

// server info ----------------------------------------------------------------
function update_info() {
  $.getJSON("/server-info/").done(function (data) {
    document.querySelector("#server-info-hostname").innerHTML =
      data["hostname"];
    document.querySelector("#server-info-server-started").innerHTML =
      data["started"];
    document.querySelector("#server-info-can-interface").innerHTML =
      data["can_interface"];
    document.querySelector("#server-info-can-interface-state").innerHTML = data[
      "can_interface_is_up"
    ]
      ? "UP"
      : "DOWN";
    document.querySelector("#server-info-can-tx-error").innerHTML = data[
      "can_tx_error"
    ]
      ? "TX_ERROR!"
      : "";
    document.querySelector("#server-info-lss-state").innerHTML =
      data["lss_state"];
  });
}

setInterval(update_info, 1000);

// Ractive --------------------------------------------------------------------
Ractive.DEBUG = false;

var ractive = Ractive({
  target: "#ractive",
  template: "#main",
  data: {
    connected: true,
    template: window.location.hash.substr(1) || "nodes",
    dots: [],
    state: "",
  },
  computed: {
    node_info: function () {
      var selected_node = this.get("selected_node");
      var state = this.get("state");

      for (var i in this.get("state")) {
        var node = state[i];

        if (node[0] == selected_node) {
          return node[1];
        }
      }

      return {};
    },
  },
});

// RPC ------------------------------------------------------------------------
var rpc_protocol = "ws://";

if (window.location.protocol == "https:") {
  rpc_protocol = "wss://";
}

var rpc = new RPC(rpc_protocol + window.location.host + "/rpc/");
rpc.DEBUG = false;

var first_connect = true;

rpc.on("close", function (rpc) {
  ractive.set("connected", false);

  setTimeout(function () {
    var dots = ractive.get("dots");
    dots.push(".");

    if (dots.length >= 4) {
      dots = [];
    }

    ractive.set("dots", dots);

    rpc.connect();
  }, 1000);
});

rpc.on("open", function (rpc) {
  if (first_connect) {
    first_connect = false;
  } else {
    window.location.reload();
  }

  ractive.set({
    connected: true,
    state: "",
  });

  rpc._topic_handler.state = function (data) {
    ractive.set("state", data);
  };

  rpc._topic_handler.isp_console = function (data) {
    ractive.set("isp_console", data);
  };

  rpc.call("subscribe", "state");
  rpc.call("subscribe", "isp_console");
});

rpc.connect();

function update_pin_info() {
  if (!ractive.get("connected")) {
    return;
  }

  var selected_node = ractive.get("selected_node");

  if (!selected_node) {
    return;
  }

  $.getJSON("/nodes/" + selected_node + "/pin-info/").done(function (data) {
    ractive.set("pin_info", data.result);
  });
}

get_firmware_files();

setInterval(function () {
  update_pin_info();
}, 1000);
