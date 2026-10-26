#include "AppIdentity.h"
#include "Voice.h"
#include <QStandardPaths>
#include <QTemporaryDir>
#include <QJsonDocument>
#include <QJsonObject>
#include <QDebug>
int main(int argc,char **argv){
 QCoreApplication app(argc,argv);
 if(qEnvironmentVariableIsSet("REGRESSION_OLD_IDENTITY")){app.setOrganizationName("local");app.setApplicationName("hermes-touch-voice.local");}
 else initializeAppIdentity(app);
 const auto expected=QStandardPaths::writableLocation(QStandardPaths::GenericDataLocation)+"/hermes-touch-voice.local";
 QDir().mkpath(expected); QFile f(expected+"/settings.json"); if(!f.open(QIODevice::WriteOnly))return 2;
 f.setPermissions(QFileDevice::ReadOwner|QFileDevice::WriteOwner);
 f.write(QJsonDocument(QJsonObject{{"base","https://127.0.0.1:1"},{"token",QString(64,'x')}}).toJson());f.close();
 Voice voice;
 const bool ok=QStandardPaths::writableLocation(QStandardPaths::AppDataLocation)==expected&&voice.configured()&&voice.findChildren<QAudioInput*>().isEmpty();
 qInfo()<< (ok?"PASS":"FAIL") << "package storage and provisioned settings" << "configured" << voice.configured() << "audioInputs" << voice.findChildren<QAudioInput*>().size();
 return ok?0:1; // No event loop, no health request, no microphone.
}
