const TARGET_PORTS = new Set([5555]);

let proxyIp = [127, 0, 0, 1];
let fakeUuid = '';

recv(function (message) {
    const proxyPort = message.port;
    if (message.proxyUrl) {
        proxyIp = Array.isArray(message.proxyIp) && message.proxyIp.length === 4
            ? message.proxyIp : [127, 0, 0, 1];
        hookConnect(proxyPort, proxyIp);
    }
    
    if (message.portableMode && message.fakeUuid) {
        fakeUuid = message.fakeUuid;
        hookHostname(); // Usually windows networking checks
        hookSystemInfo();
    }
    
    send('hooks_ready');
});


function hookConnect(proxyPort, proxyIp) {
    const connectPtr = Module.getExportByName("ws2_32.dll", "connect");

    Interceptor.attach(connectPtr, {
        onEnter(args) {
            try {
                const sockaddr = args[1];
                const family = sockaddr.readU16();

                // add(nb octet) permet de déplacer le point à nb d'octet apres sockaddr
                if (family === 2) { // IPV4
                    const port = (sockaddr.add(2).readU8() << 8) | sockaddr.add(3).readU8();

                    if (!TARGET_PORTS.has(port)) return

                    sockaddr.add(4).writeByteArray(proxyIp);
                    sockaddr.add(2).writeU8((proxyPort >> 8) & 0xFF);
                    sockaddr.add(3).writeU8(proxyPort & 0xFF);

                } else if (family === 23) { // IPV6
                    const port =
                        (sockaddr.add(2).readU8() << 8) |
                        sockaddr.add(3).readU8();

                    if (!TARGET_PORTS.has(port)) return;

                    const ipv6 = sockaddr.add(8);

                    ipv6.writeByteArray([
                        0x00, 0x00, 0x00, 0x00, // 0-3
                        0x00, 0x00, 0x00, 0x00, // 4-7
                        0x00, 0x00, 0xFF, 0xFF, // 8-11
                        proxyIp[0], proxyIp[1], proxyIp[2], proxyIp[3]
                    ]);

                    sockaddr.add(2).writeU8((proxyPort >> 8) & 0xFF);
                    sockaddr.add(3).writeU8(proxyPort & 0xFF);
                }
            }
            catch (err) {
                console.info(err.message);
            }
        }
    });
}

function hookHostname() {
    try {
        const hostnameBuffers = {};
        const fakeHostname = "DESKTOP-" + fakeUuid.substring(0, 7).toUpperCase();

        const gethostnamePtr = Module.getExportByName("ws2_32.dll", "gethostname");
        if (gethostnamePtr) {
            Interceptor.attach(gethostnamePtr, {
                onEnter(args) { hostnameBuffers[args[0].toString()] = ptr(args[0]); },
                onLeave() {
                    for (const key in hostnameBuffers) {
                        try {
                            hostnameBuffers[key].writeAnsiString(fakeHostname + String.fromCharCode(0));
                        } catch (e) {}
                        delete hostnameBuffers[key];
                    }
                }
            });
        }
    } catch (err) {
        console.log(`ERREUR hookHostname: ${err.message}`);
    }
}

function hookSystemInfo() {
    try {
        if (typeof Il2Cpp !== 'undefined') {
            Il2Cpp.perform(function() {
                const SystemInfo = Il2Cpp.domain.assembly("UnityEngine.CoreModule").image.class("UnityEngine.SystemInfo");
                const get_deviceUniqueIdentifier = SystemInfo.method("get_deviceUniqueIdentifier");
                get_deviceUniqueIdentifier.implementation = function() {
                    return Il2Cpp.string(fakeUuid);
                };
            });
        } else {
            console.log("frida-il2cpp-bridge not loaded, skipping UnityEngine.SystemInfo intercept");
        }
    } catch (e) {
        console.log(`ERREUR hookSystemInfo: ${e.message}`);
    }
}
