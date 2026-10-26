#include <QGuiApplication>
#include <QQmlApplicationEngine>
#include <QQmlContext>
#include "AppIdentity.h"
#include "Voice.h"
#include <QQuickWindow>
#include <QQuickItem>
#include <QDebug>
#include <QTimer>
int main(int argc,char **argv){
 QGuiApplication app(argc,argv);
 initializeAppIdentity(app);
 Voice voice;app.installEventFilter(voice.powerActivity());QQmlApplicationEngine engine;engine.rootContext()->setContextProperty("voice",&voice);
 engine.load(QUrl(QStringLiteral("qrc:/Main.qml")));
 QObject::connect(&voice,&Voice::changed,&app,[&]{qInfo() << "Native state" << voice.state() << "connected" << voice.connected();});
 for(auto window:QGuiApplication::allWindows())if(auto quick=qobject_cast<QQuickWindow*>(window)){
  QObject::connect(quick,&QQuickWindow::frameSwapped,quick,[quick]{if(!quick->property("firstFrameLogged").toBool()){quick->setProperty("firstFrameLogged",true);qInfo() << "Native first frame" << quick->size();}});
 }
 QTimer::singleShot(3000,&app,[&]{qInfo() << "Native startup" << "windows" << QGuiApplication::allWindows().size() << "state" << voice.state() << "connected" << voice.connected() << "configured" << voice.configured() << "audioInputs" << voice.findChildren<QAudioInput*>().size();});
 return engine.rootObjects().isEmpty()?1:app.exec();
}
