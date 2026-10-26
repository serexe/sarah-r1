import QtQuick 2.12
import Lomiri.Components 1.3
import QtQuick.Window 2.12

Window {
    visible: true
    width: 480; height: 640

MainView {
    id: root
    objectName: "mainView"
    applicationName: "hermes-touch-voice.local"
    anchors.fill: parent
    backgroundColor: "#151817"
    property bool setup: !voice.configured
    property bool confirmNew: false
    property bool active: ["starting", "listening", "transcribing", "thinking", "confirming", "acting", "preparing", "reconnecting"].indexOf(voice.state) >= 0
    Component.onCompleted: { if(Qt.application.state === Qt.ApplicationActive) voice.foregrounded(); else voice.suspended(); }
    Connections { target: Qt.application; onStateChanged: { if(Qt.application.state !== Qt.ApplicationActive) voice.suspended(); else voice.foregrounded(); } }
    Item {
        id: surface
        anchors.fill: parent
        anchors.margins: 28
        Text { id: title; text: "S.A.R.A.H"; color: "#f5f3ed"; font.pixelSize: 34; font.bold: true; anchors.top: parent.top }
        Row {
            id: status; anchors.top: title.bottom; anchors.topMargin: 10; spacing: 10
            Rectangle { width: 10; height: 10; radius: 5; color: voice.connected ? "#ff742e" : "#babe bd".replace(" ", ""); anchors.verticalCenter: parent.verticalCenter }
            Text { color: "#babebd"; font.pixelSize: 19; text: (voice.connected ? "Connected" : "Disconnected") + " · " + voice.state.charAt(0).toUpperCase() + voice.state.slice(1) }
        }
        Rectangle {
            id: secondary; width: parent.width; height: 56; radius: 16; color: "#202523"; border.color: "#48504b"
            anchors.top: status.bottom; anchors.topMargin: 24
            Text { anchors.centerIn: parent; color: "#f5f3ed"; font.pixelSize: 21; text: root.active ? (voice.state === "listening" ? "×  Cancel recording" : "×  Cancel request") : (root.confirmNew ? "Confirm new conversation?" : "+  New conversation") }
            MouseArea { anchors.fill: parent; onClicked: { if(root.active) voice.cancel(); else if(voice.transcript.length && !root.confirmNew) root.confirmNew=true; else {root.confirmNew=false;voice.newConversation();} } }
        }
        Rectangle { id: divider; height: 1; color: "#353c38"; width: parent.width; anchors.top: secondary.bottom; anchors.topMargin: 24 }
        Flickable {
            id: scroll; anchors.top: divider.bottom; anchors.topMargin: 22; anchors.bottom: main.top; anchors.bottomMargin: 24; width: parent.width
            clip: true; contentWidth: width; contentHeight: history.height
            Text { id: history; width: scroll.width; wrapMode: Text.Wrap; textFormat: Text.PlainText; color: "#f5f3ed"; font.pixelSize: 25; lineHeight: 1.25; text: voice.transcript.length ? voice.transcript.replace(/(^|\n\n)HERMES\n/g, "$1S.A.R.A.H\n") : "Your conversation appears here.\n\nTap to talk when secure companion is available." }
        }
        Rectangle {
            id: main; width: parent.width; height: 112; radius: 28; anchors.bottom: footer.top; anchors.bottomMargin: 24
            property bool available: voice.state === "armed" || voice.state === "ready" || voice.state === "listening" || voice.state === "speaking"
            color: available ? "#ff742e" : "#48504b"
            Text { anchors.centerIn: parent; color: "#151817"; font.pixelSize: 28; font.bold: true; text: voice.state === "listening" ? "■  Stop & send" : voice.state === "speaking" ? "■  Stop audio" : root.active ? "Working…" : main.available ? "●  Tap to talk" : "Reconnect first" }
            MouseArea { anchors.fill: parent; enabled: main.available; onClicked: {root.confirmNew=false;voice.primary();} }
        }
        Text {
            id: footer; anchors.bottom: parent.bottom; width: parent.width; height: 32; horizontalAlignment: Text.AlignHCenter
            font.pixelSize: 16; color: "#babebd"; elide: Text.ElideRight; text: voice.detail
            MouseArea { anchors.fill: parent; onClicked: root.setup=true }
        }
    }
    Rectangle {
        visible: voice.state === "confirming"; anchors.fill: parent; color: "#151817"; z: 2
        Column {
            anchors { left: parent.left; right: parent.right; top: parent.top; margins: 28 } spacing: 24
            Text { text: "Confirm Home Assistant"; color: "#f5f3ed"; font.pixelSize: 26 }
            Text { text: voice.detail; width: parent.width; wrapMode: Text.Wrap; textFormat: Text.PlainText; color: "#f5f3ed"; font.pixelSize: 24 }
            Button { text: "Confirm exact action once"; width: parent.width; onClicked: voice.confirmAction(true) }
            Button { text: "Deny action"; width: parent.width; onClicked: voice.confirmAction(false) }
            Button { text: "Cancel request"; width: parent.width; onClicked: voice.cancel() }
        }
    }
    Rectangle {
        visible: root.setup; anchors.fill: parent; color: "#151817"
        Column {
            anchors { left: parent.left; right: parent.right; top: parent.top; margins: 28 } spacing: 18
            Text { text: "Secure companion"; color: "#f5f3ed"; font.pixelSize: 30 }
            Text { width: parent.width; wrapMode: Text.Wrap; text: "HTTPS origin and revocable device token only. Never enter Hermes, Codex, or Home Assistant credentials."; color: "#babebd"; font.pixelSize: 20 }
            TextField { id: endpoint; width: parent.width; placeholderText: "https://companion.example.invalid"; inputMethodHints: Qt.ImhUrlCharactersOnly; font.pixelSize: 20 }
            TextField { id: token; width: parent.width; placeholderText: "Device token"; echoMode: TextInput.Password; inputMethodHints: Qt.ImhSensitiveData | Qt.ImhNoPredictiveText; font.pixelSize: 20 }
            Button { text: "Save & reconnect"; width: parent.width; onClicked: { voice.configure(endpoint.text,token.text); token.text="";root.setup=false; } }
            Button { text: "Reconnect existing"; width: parent.width; onClicked: {root.setup=false;voice.reconnect();} }
            Text { width: parent.width; wrapMode: Text.Wrap; text: voice.detail; color: "#ff742e"; font.pixelSize: 19 }
        }
    }
}
}
