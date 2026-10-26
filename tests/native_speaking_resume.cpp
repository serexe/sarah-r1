// Production Qt -> actual make_app. Playback/capture boundaries overridden only.
#include "Voice.h"
#include <QCoreApplication>
#include <QTemporaryDir>
#include <QStandardPaths>
#include <QThread>
#include <QJsonDocument>
#include <QJsonObject>
#include <QDebug>
#include <QtEndian>
class StubVoice:public Voice {public:int plays=0,captures=0;protected:void startCapture()override{++captures;}void playReply(const QString&)override{++plays;}};
static void drain(int ms=100){QElapsedTimer t;t.start();while(t.elapsed()<ms){QCoreApplication::processEvents();QThread::msleep(1);}}
static void until(std::function<bool()> done,int ms=2500){QElapsedTimer t;t.start();while(!done()&&t.elapsed()<ms)drain(10);}
class PendingStartRegression{public:static int run(){
 int failures=0,expected=0;auto check=[&](bool ok,const char*n){qInfo().noquote()<<(ok?"PASS":"FAIL")<<n;if(!ok)++failures;};
 QByteArray wav;auto p16=[&](quint16 n){n=qToLittleEndian(n);wav.append((char*)&n,2);};auto p32=[&](quint32 n){n=qToLittleEndian(n);wav.append((char*)&n,4);};wav.append("RIFF",4);p32(8036);wav.append("WAVEfmt ",8);p32(16);p16(1);p16(1);p32(16000);p32(32000);p16(2);p16(16);wav.append("data",4);p32(8000);wav.append(QByteArray(8000,0));
 for(QString mode:{"resume","cancel","fetch_suspend","fetch_stop","play_suspend","play_stop"}){
  qInfo()<<"SCENARIO"<<mode;
  QFile::remove(QStandardPaths::writableLocation(QStandardPaths::AppDataLocation)+"/settings.json");StubVoice v;drain();v.m_base="http://127.0.0.1:38479";v.m_token=QString(48,'x');v.m_foreground=true;v.m_poll.setInterval(200);
  v.request("POST","/fixture/mode/"+mode,"{}",[](QByteArray,int){});drain();
  bool created=false;v.request("POST","/v1/conversations","{}",[&](QByteArray b,int c){v.m_conversation=QJsonDocument::fromJson(b).object()["conversation"].toString();created=c==201;});drain();check(created,"actual conversation created");
  v.submitClip(wav);++expected;drain(180);const QString turn=v.m_turn;
  check(!turn.isEmpty()&&v.state()=="preparing","server TTS preparation distinct from local speaking");
  if(mode=="resume"){
   v.suspended();v.foregrounded();drain(1100);
   check(v.m_turn.isEmpty()&&v.m_request.isEmpty()&&v.transcript().count("YOU\n")==1&&v.transcript().count("S.A.R.A.H\n")==1,"suspend during server TTS consumes terminal transcript once");
   const QString text=v.transcript();v.reconnect();v.reconnect();drain(200);v.poll();drain();check(v.transcript()==text,"repeated reconnect cannot duplicate terminal transcript");
  }else if(mode=="cancel"){
   v.cancel();drain(900);QString state;v.request("GET","/v1/turns/"+turn,{},[&](QByteArray b,int c){if(c==200)state=QJsonDocument::fromJson(b).object()["state"].toString();});drain();
   check(state=="cancelled"&&v.m_request.isEmpty()&&v.m_turn.isEmpty()&&v.transcript().isEmpty(),"Cancel during preparation cancels retained server turn");
  }else{
   until([&]{return v.m_turn.isEmpty()&&!v.transcript().isEmpty();});check(v.state()=="speaking"&&v.m_turn.isEmpty()&&v.transcript().count("S.A.R.A.H\n")==1,"terminal consumed before local audio");
   const QString text=v.transcript();const bool fetching=mode.startsWith("fetch");if(!fetching)until([&]{return v.plays==1;});check(v.plays==(fetching?0:1),"delayed fetch or overridden local playback reached");
   v.reconnect();drain();check(v.state()=="speaking","reconnect preserves owned local fetch/playback");
   if(mode.endsWith("suspend")){v.suspended();v.foregrounded();}else v.primary();
   drain(1200);check(v.state()!="speaking"&&v.plays==(fetching?0:1)&&v.transcript()==text,"suspend or Stop discards local audio; written reply kept");
   v.reconnect();drain();check(v.plays==(fetching?0:1),"foreground/reconnect never restarts discarded audio");
  }
  int uploads=-1,calls=-1,turns=-1,audio=-1;v.request("GET","/fixture/stats",{},[&](QByteArray b,int c){auto o=QJsonDocument::fromJson(b).object();if(c==200){uploads=o["uploads"].toInt();calls=o["calls"].toInt();turns=o["turns"].toInt();audio=o["audio"].toInt();}});drain();
  check(uploads==expected&&calls==expected&&turns==expected,"one wire POST and provider admission per explicit upload");
  check(audio==qMax(0,expected-2),"audio fetched at most once; no redispatch on resume/reconnect");
  check(v.captures==0&&v.findChildren<QAudioInput*>().isEmpty()&&!QFile::exists(v.storage()+"/capture.wav"),"no capture hardware or file");
 }
 qInfo()<<"failures="<<failures;return failures?1:0;
}};
int main(int argc,char**argv){QTemporaryDir home;qputenv("XDG_DATA_HOME",home.path().toUtf8());QCoreApplication app(argc,argv);app.setApplicationName("r1-native-speaking-resume");return PendingStartRegression::run();}
