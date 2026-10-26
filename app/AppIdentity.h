#pragma once
#include <QCoreApplication>
// Click confinement and coordinator provisioning use the package data directory.
// A nonempty organization inserts an extra, unprovisioned directory.
inline void initializeAppIdentity(QCoreApplication &app) {
    app.setOrganizationName("");
    app.setApplicationName("hermes-touch-voice.local");
}
