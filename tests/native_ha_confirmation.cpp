// Production Qt -> production make_app/Codex tool parser -> loopback HA.
#include "Voice.h"
#include <QCoreApplication>
#include <QTemporaryDir>
#include <QStandardPaths>
#include <QThread>
#include <QJsonDocument>
#include <QDebug>
#include <QtEndian>
class StubVoice:public Voice {public:int captures=0,plays=0;protected:void startCapture()override{++captures;}void playReply(const QString&)override{++plays;}};
static void drain(int ms=60){QElapsedTimer t;t.start();while(t.elapsed()<ms){QCoreApplication::processEvents();QThread::msleep(1);}}
static void until(std::function<bool()> done){QElapsedTimer t;t.start();while(!done()&&t.elapsed()<3000)drain(10);}
class PendingStartRegression{public:static int run(){
 int failures=0;auto check=[&](bool ok,const char*n){qInfo().noquote()<<(ok?"PASS":"FAIL")<<n;if(!ok)++failures;};
 QByteArray wav;auto p16=[&](quint16 n){n=qToLittleEndian(n);wav.append((char*)&n,2);};auto p32=[&](quint32 n){n=qToLittleEndian(n);wav.append((char*)&n,4);};wav.append("RIFF",4);p32(8036);wav.append("WAVEfmt ",8);p32(16);p16(1);p16(1);p32(16000);p32(32000);p16(2);p16(16);wav.append("data",4);p32(8000);wav.append(QByteArray(8000,0));
 for(bool accept:{true,false}){
  QFile::remove(QStandardPaths::writableLocation(QStandardPaths::AppDataLocation)+"/settings.json");StubVoice v;drain();v.m_base=qEnvironmentVariable("R1_FIXTURE_URL");v.m_token=QString(48,'a');v.m_foreground=true;v.m_poll.setInterval(30);
  bool created=false;v.request("POST","/v1/conversations","{}",[&](QByteArray b,int c){v.m_conversation=QJsonDocument::fromJson(b).object()["conversation"].toString();created=c==201;});until([&]{return created;});check(created,"owned conversation created");
  v.submitClip(wav);until([&]{return v.m_turn.isEmpty()&&!v.transcript().isEmpty();});
  check(v.state()!="confirming"&&v.m_confirmation.isEmpty(),"routine no native approval or nonce");
  check(v.m_turn.isEmpty(),"direct routine terminal reconciled");
  check(v.transcript().contains("State verified."),"authoritative routine text truthful");
  QString before=v.transcript();v.confirmAction(accept);v.confirmAction(accept);drain(100);
  check(v.transcript()==before&&v.m_confirmation.isEmpty(),"obsolete approval input cannot redispatch");
  QString text=v.transcript();v.suspended();v.foregrounded();v.reconnect();drain(150);check(v.transcript()==text,"reconnect no duplicate transcript or approval");
  check(v.captures==0&&!QFile::exists(v.storage()+"/capture.wav"),"no mic capture");
 }
 qInfo()<<"failures="<<failures;return failures?1:0;
}};
int main(int argc,char**argv){QTemporaryDir home;qputenv("XDG_DATA_HOME",home.path().toUtf8());QCoreApplication app(argc,argv);app.setApplicationName("r1-native-ha");return PendingStartRegression::run();}
