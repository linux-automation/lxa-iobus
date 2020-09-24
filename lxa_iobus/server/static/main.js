// helper functions -----------------------------------------------------------
function toggle_locator(node_address) {
    $.post('/nodes/' + node_address + '/toggle-locator/');

    update_pin_info();
};

function toggle_pin(node_address, pin_name) {
    $.post('/nodes/' + node_address + '/pins/' + pin_name + '/', {
        value: 'toggle',
    });

    update_pin_info();
};

// Ractive --------------------------------------------------------------------
Ractive.DEBUG = false;

var ractive = Ractive({
    target: '#ractive',
    template: '#main',
    data: {
        connected: true,
        template: 'nodes',
        dots: [],
        state: '',
    },
    computed: {
        node_info: function() {
            var selected_node = this.get('selected_node');
            var state = this.get('state');

            for(var i in this.get('state')) {
                var node = state[i];

                if(node[0] == selected_node) {
                    return node[1];
                };
            };

            return {};
        },
    },
});

// RPC ------------------------------------------------------------------------
var rpc_protocol = 'ws://';

if(window.location.protocol == 'https:') {
    rpc_protocol = 'wss://';
}

var rpc = new RPC(rpc_protocol + window.location.host + '/rpc/');
rpc.DEBUG = false;

rpc.on('close', function(rpc) {
    ractive.set('connected', false);

    setTimeout(function() {
        var dots = ractive.get('dots');
        dots.push('.');

        if(dots.length >= 4) {
            dots = [];
        }

        ractive.set('dots', dots);

        rpc.connect();
    }, 1000);
});

rpc.on('open', function(rpc) {
    ractive.set({
        connected: true,
        state: '',
    });

    rpc._topic_handler.state = function(data) {
        ractive.set('state', data);
    };

    rpc.call('subscribe', 'state');
});

rpc.connect();

function update_pin_info() {
    if(!ractive.get('connected')) {
        return;
    };

    var selected_node = ractive.get('selected_node');

    if(!selected_node) {
        return;
    };

    $.getJSON('/nodes/' + selected_node + '/pin-info/').done(function(data) {
        ractive.set('pin_info', data.result);
    });

};

setInterval(function() {
    update_pin_info();
}, 1000);
