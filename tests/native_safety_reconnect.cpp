// Hardware-free native lifecycle: real Qt network, synthetic localhost responses.
#include "Voice.h"
#include <QCoreApplication>
#include <QTcpServer>
#include <QTcpSocket>
#include <QTemporaryDir>
#include <QStandardPaths>
#include <QThread>
#include <QJsonDocument>
#include <QJsonObject>
#include <QDebug>
#include <QDir>
class StubVoice:public Voice{public:int captures=0;protected:void startCapture()override{++captures;}};
static void drain(int ms=100){QElapsedTimer t;t.start();while(t.elapsed()<ms){QCoreApplication::processEvents();QThread::msleep(1);}}
class Server:public QTcpServer{public:
 QList<QTcpSocket*> health,polls,posts;int uploads=0,lookups=0,cancels=0;QString key;bool terminal=false;
 static void reply(QTcpSocket*s,int c,QByteArray b){s->write("HTTP/1.1 "+QByteArray::number(c)+" OK\r\nContent-Type: application/json\r\nContent-Length: "+QByteArray::number(b.size())+"\r\nConnection: close\r\n\r\n"+b);s->disconnectFromHost();}
 Server(){listen(QHostAddress::LocalHost,0);connect(this,&QTcpServer::newConnection,this,[this]{while(hasPendingConnections()){auto s=nextPendingConnection();connect(s,&QTcpSocket::readyRead,this,[this,s]{auto b=s->property("b").toByteArray()+s->readAll();s->setProperty("b",b);if(s->property("done").toBool()||!b.contains("\r\n\r\n"))return;s->setProperty("done",true);
 if(b.startsWith("GET /v1/health "))health.append(s);
 else if(b.startsWith("POST /v1/turns ")){++uploads;posts.append(s);for(auto line:b.split('\n'))if(line.toLower().startsWith("idempotency-key:"))key=QString::fromUtf8(line.mid(line.indexOf(':')+1).trimmed());}
 else if(b.startsWith("GET /v1/requests/")){++lookups;reply(s,200,"{\"id\":\"accepted\",\"conversation\":\"conv\",\"state\":\"thinking\"}");}
 else if(b.startsWith("POST /v1/turns/accepted/cancel")){++cancels;terminal=true;reply(s,200,"{}");}
 else if(b.startsWith("GET /v1/turns/")){if(terminal)reply(s,200,"{\"state\":\"cancelled\",\"detail\":\"cancelled\"}");else polls.append(s);}
 else reply(s,404,"{}");});}});}
 void ready(){auto q=health;health.clear();for(auto s:q)reply(s,200,"{\"connected\":true,\"ready\":true}");drain();}
};
class PendingStartRegression{public:static int run(){int failures=0;auto check=[&](bool ok,const char*n){qInfo().noquote()<<(ok?"PASS":"FAIL")<<n;if(!ok)++failures;};
 auto setup=[](StubVoice&v,Server&s){v.m_base="http://127.0.0.1:"+QString::number(s.serverPort());v.m_token=QString(48,'x');v.m_foreground=true;v.m_ready=true;v.m_conversation="conv";v.m_turn.clear();v.m_request.clear();v.set("armed","test");};
 {Server s;StubVoice v;drain();setup(v,s);v.reconnect();drain();v.primary();v.set("listening","test recording");v.m_limit.start(500);s.ready();check(v.state()=="listening","late health preserves visible recording");v.set("armed","injected presentation drift");v.m_limit.start(30);drain(100);check(!v.m_limit.isActive()&&v.detail().contains("Recording discarded"),"hard deadline independent of presentation");check(v.captures==1,"one explicit capture");}
 {Server s;StubVoice v;drain();setup(v,s);v.primary();v.set("armed","injected presentation drift");v.primary();check(v.captures==1,"duplicate input guard survives presentation drift");v.cancel();}
 {Server s;StubVoice v;drain();setup(v,s);v.m_turn="accepted";v.poll();v.poll();drain();check(s.polls.size()==1,"turn poll serialized");auto pending=s.polls;for(auto p:pending)Server::reply(p,200,"{\"state\":\"done\",\"detail\":\"reply\",\"transcript\":\"hello\",\"audio\":false}");drain();check(v.transcript().count("YOU\n")==1,"terminal transcript exactly once");v.m_turn="accepted";v.poll();drain();v.m_turn="new-turn";v.set("listening","new owner");for(auto p:s.polls.mid(pending.size()))Server::reply(p,200,"{\"state\":\"done\",\"detail\":\"stale\"}");drain();check(v.m_turn=="new-turn"&&v.state()=="listening","stale poll cannot overwrite newer owner");}
 for(QString mode:{"lost","suspend","cancel","reset","restart"}){Server s;StubVoice v;drain();setup(v,s);v.submitClip("synthetic clip; never hardware");drain();check(s.uploads==1&&!v.m_request.isEmpty(),"POST identity persisted before response");if(mode=="lost"){s.posts.first()->abort();drain();}else v.suspended();if(mode=="reset"){v.newConversation();s.ready();check(v.m_request.isEmpty()&&v.m_turn.isEmpty(),"reset isolates old upload identity");continue;}if(mode=="restart"){StubVoice restored;drain();restored.m_base=v.m_base;restored.m_token=v.m_token;restored.foregrounded();drain();s.ready();check(restored.m_turn=="accepted","process restart reconciles persisted request");restored.m_poll.stop();}else{if(mode=="cancel")v.cancel();v.foregrounded();drain();s.ready();check(s.lookups>=1,"resume reconciles request key");if(mode=="cancel"){drain();check(s.cancels==1,"unknown accepted upload cancellation reconciled");}else check(v.m_turn=="accepted","lost or suspended 202 recovers turn");}check(s.uploads==1,"reconciliation never redispatches audio");v.m_poll.stop();v.m_turn.clear();v.m_request.clear();v.save();}
 {Server s;StubVoice v;drain();setup(v,s);QString path=v.storage()+"/settings.json";QFile::remove(path);QDir().mkdir(path);v.submitClip("synthetic");drain();check(s.uploads==0&&v.state()=="error","failed durable identity write blocks audio POST");QDir().rmdir(path);}
 check(!QFile::exists(QStandardPaths::writableLocation(QStandardPaths::AppDataLocation)+"/capture.wav"),"no microphone file");qInfo()<<"failures="<<failures;return failures?1:0;}};
int main(int argc,char**argv){QTemporaryDir home;qputenv("XDG_DATA_HOME",home.path().toUtf8());QCoreApplication app(argc,argv);app.setApplicationName("r1-safety-reconnect");return PendingStartRegression::run();}
