// Production Qt client + actual Python make_app, namespace-local fixture only.
#include "Voice.h"
#include <QCoreApplication>
#include <QTemporaryDir>
#include <QStandardPaths>
#include <QThread>
#include <QJsonDocument>
#include <QJsonObject>
#include <QDebug>
#include <QtEndian>
static void drain(int ms=100){QElapsedTimer t;t.start();while(t.elapsed()<ms){QCoreApplication::processEvents();QThread::msleep(1);}}
class PendingStartRegression{public:static int run(){int failures=0;auto check=[&](bool ok,const char*n){qInfo().noquote()<<(ok?"PASS":"FAIL")<<n;if(!ok)++failures;};
 QByteArray wav;auto p16=[&](quint16 n){n=qToLittleEndian(n);wav.append((char*)&n,2);};auto p32=[&](quint32 n){n=qToLittleEndian(n);wav.append((char*)&n,4);};wav.append("RIFF",4);p32(8036);wav.append("WAVEfmt ",8);p32(16);p16(1);p16(1);p32(16000);p32(32000);p16(2);p16(16);wav.append("data",4);p32(8000);wav.append(QByteArray(8000,0));
 int expected=0;
 for(QString mode:{"lost","suspend","restart","cancel","reset"}){
  QFile::remove(QStandardPaths::writableLocation(QStandardPaths::AppDataLocation)+"/settings.json");Voice v;drain();v.m_base="http://127.0.0.1:38479";v.m_token=QString(48,'x');v.m_foreground=true;bool created=false;
  v.request("POST","/v1/conversations","{}",[&](QByteArray b,int c){v.m_conversation=QJsonDocument::fromJson(b).object()["conversation"].toString();created=c==201;});drain();check(created,"actual bridge conversation created");v.submitClip(wav);++expected;drain(100);QString key=v.m_request;
  if(mode!="lost")v.suspended();
  if(mode=="cancel")v.cancel();
  if(mode=="reset"){v.newConversation();drain(600);check(v.m_request.isEmpty()&&v.m_turn.isEmpty()&&v.transcript().isEmpty(),"reset isolates accepted lost202");}
  else if(mode=="restart"){Voice restored;drain();restored.foregrounded();drain(2200);check(restored.m_request.isEmpty()&&restored.transcript().contains("fixture reply"),"persisted native restart finds actual bridge turn");}
  else{drain(400);v.foregrounded();drain(700);check(v.m_request.isEmpty()&&v.m_turn.isEmpty(),"actual bridge reconciliation terminates");check(mode=="cancel"?!v.m_cancelPending:v.transcript().contains("fixture reply"),"actual lost202 resume or cancel outcome");}
  int turns=-1,calls=-1,cancelled=-1;v.request("GET","/fixture/stats",{},[&](QByteArray b,int c){auto o=QJsonDocument::fromJson(b).object();if(c==200){turns=o["turns"].toInt();calls=o["calls"].toInt();cancelled=o["cancelled"].toInt();}});drain();check(turns==expected&&calls==expected&&cancelled==(expected>=4?1:0),"exactly one actual provider admission per upload; cancellation durable");
  check(v.findChildren<QAudioInput*>().isEmpty()&&!QFile::exists(v.storage()+"/capture.wav"),"integrated native no audio hardware or capture file");
 }
 qInfo()<<"failures="<<failures;return failures?1:0;}};
int main(int argc,char**argv){QTemporaryDir home;qputenv("XDG_DATA_HOME",home.path().toUtf8());QCoreApplication app(argc,argv);app.setApplicationName("r1-native-actual-bridge");return PendingStartRegression::run();}
