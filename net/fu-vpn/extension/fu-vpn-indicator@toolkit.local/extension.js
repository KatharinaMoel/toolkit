// VPN-Symbol in der Leiste fuer den fu-vpn-Tunnel (Skript: ~/.local/bin/fu-vpn,
// Quelle: toolkit net/fu-vpn).
// An, solange die Schnittstelle existiert, sonst durchgestrichen.
// Menue: Verbinden bzw. Trennen, Status.
import GLib from 'gi://GLib';
import GObject from 'gi://GObject';
import St from 'gi://St';

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

const IFACE_PATH = '/sys/class/net/fu-vpn';
const POLL_SECONDS = 3;
const FU_VPN = GLib.build_filenamev([GLib.get_home_dir(), '.local', 'bin', 'fu-vpn']);

function runInTerminal(args) {
    GLib.spawn_async(null, ['ptyxis', '-s', '--title=FU-VPN', '--', FU_VPN, ...args],
        null, GLib.SpawnFlags.SEARCH_PATH, null);
}

class FuVpnIndicator extends PanelMenu.Button {
    static {
        GObject.registerClass(this);
    }

    constructor() {
        super(0.5, 'FU-VPN');

        this._icon = new St.Icon({style_class: 'system-status-icon'});
        this.add_child(this._icon);

        this._title = new PopupMenu.PopupMenuItem('', {reactive: false});
        this.menu.addMenuItem(this._title);
        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        this._toggle = new PopupMenu.PopupMenuItem('');
        this._toggle.connect('activate', () => runInTerminal(['toggle', '--window']));
        this.menu.addMenuItem(this._toggle);

        const status = new PopupMenu.PopupMenuItem('Status');
        status.connect('activate', () => runInTerminal(['status', '--window']));
        this.menu.addMenuItem(status);

        this.setConnected(false);
    }

    setConnected(connected) {
        this._icon.icon_name = connected ? 'network-vpn-symbolic' : 'network-vpn-disabled-symbolic';
        this._title.label.text = connected ? 'FU-VPN verbunden' : 'FU-VPN aus';
        this._toggle.label.text = connected ? 'Trennen' : 'Verbinden';
    }
}

export default class FuVpnIndicatorExtension extends Extension {
    enable() {
        this._indicator = new FuVpnIndicator();
        Main.panel.addToStatusArea(this.uuid, this._indicator);
        this._update();
        this._timeoutId = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, POLL_SECONDS, () => {
            this._update();
            return GLib.SOURCE_CONTINUE;
        });
    }

    disable() {
        if (this._timeoutId) {
            GLib.source_remove(this._timeoutId);
            this._timeoutId = null;
        }
        this._indicator.destroy();
        this._indicator = null;
    }

    _update() {
        this._indicator.setConnected(GLib.file_test(IFACE_PATH, GLib.FileTest.EXISTS));
    }
}
