// Ractive --------------------------------------------------------------------
Ractive.DEBUG = false;

var ractive = Ractive({
    target: '#ractive',
    template: '#main',
    data: {
        connected: true,
        dots: [],
        state: '',
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
