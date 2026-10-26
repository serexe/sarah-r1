// Offline native launch regression. Uses production Voice and compiled QML resources.
// Run only in the isolated SDK/QEMU harness documented in evidence/r1-native-launch-repair.md.
#include <QGuiApplication>
#include <QQmlApplicationEngine>
#include <QQmlContext>
#include <QQuickItem>
#include <QQuickWindow>
#include <QStandardPaths>
#include <QDebug>
#include "AppIdentity.h"
#include "Voice.h"

int main(int argc, char **argv) {
    QGuiApplication app(argc, argv);
    initializeAppIdentity(app);
    Voice voice;
    QQmlApplicationEngine engine;
    bool qmlWarnings = false;
    QObject::connect(&engine, &QQmlEngine::warnings, &app,
                     [&qmlWarnings](const QList<QQmlError> &warnings) {
        for (const auto &warning : warnings) {
            // Existing Qt 5.15 deprecation, unrelated to launch failure.
            if (!warning.description().contains("Implicitly defined onFoo properties"))
                qmlWarnings = true;
        }
    });
    engine.rootContext()->setContextProperty("voice", &voice);
    engine.load(QUrl(QStringLiteral("qrc:/Main.qml")));
    if (engine.rootObjects().size() != 1) return 1;
    auto window = qobject_cast<QQuickWindow *>(engine.rootObjects().first());
    auto root = window ? window->findChild<QQuickItem *>("mainView") : nullptr;
    if (!root || root->window() != window) return 2;
    QTimer::singleShot(1500, &app, [&] {
        const auto storage = QStandardPaths::writableLocation(QStandardPaths::AppDataLocation);
        const auto frame = window->grabWindow();
        const bool rendered = !frame.isNull() && frame.width() == 480 && frame.height() == 640 &&
            frame.save("/project/native-smoke/native-launch.png");
        const bool safe = rendered && !voice.configured() && !voice.connected() &&
            voice.state() == "offline" && root->property("setup").toBool() &&
            root->window() && root->window()->isVisible() &&
            voice.findChildren<QAudioInput *>().isEmpty() &&
            !QFile::exists(storage + "/capture.wav") && !qmlWarnings;
        qInfo().noquote() << (safe ? "PASS" : "FAIL")
            << "rootObjects=" << engine.rootObjects().size()
            << "objectName=" << root->objectName()
            << "rendered=" << rendered
            << "visible=" << (root->window() && root->window()->isVisible())
            << "setup=" << root->property("setup").toBool()
            << "state=" << voice.state()
            << "configured=" << voice.configured()
            << "audioInputs=" << voice.findChildren<QAudioInput *>().size()
            << "qmlErrors=" << qmlWarnings;
        app.exit(safe ? 0 : 3);
    });
    return app.exec();
}
