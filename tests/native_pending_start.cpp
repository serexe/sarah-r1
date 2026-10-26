// Controlled localhost HTTP only. Capture override never enumerates/opens audio.
#include "Voice.h"
#include <QCoreApplication>
#include <QTcpServer>
#include <QTcpSocket>
#include <QTemporaryDir>
#include <QStandardPaths>
#include <QElapsedTimer>
#include <QThread>
#include <QJsonDocument>
#include <QJsonObject>
#include <QDebug>
#include <functional>

class StubVoice : public Voice {
public:
    int captures=0;
protected:
    void startCapture() override { ++captures; }
};
class ControlledServer : public QTcpServer {
public:
    QList<QTcpSocket*> pending;
    int creates=0;
    ControlledServer() {
        listen(QHostAddress::LocalHost,0);
        connect(this,&QTcpServer::newConnection,this,[this]{
            while(hasPendingConnections()) {
                auto s=nextPendingConnection();
                connect(s,&QTcpSocket::readyRead,this,[this,s]{
                    auto bytes=s->property("bytes").toByteArray()+s->readAll();
                    s->setProperty("bytes",bytes);
                    if(s->property("handled").toBool()||!bytes.contains("\r\n\r\n"))return;
                    s->setProperty("handled",true);
                    if(bytes.startsWith("POST /v1/conversations ")){++creates;pending.append(s);}
                    else reply(s,200,"{\"connected\":true,\"ready\":true}");
                });
            }
        });
    }
    static void reply(QTcpSocket *s,int code,QByteArray body) {
        s->write("HTTP/1.1 "+QByteArray::number(code)+" OK\r\nContent-Type: application/json\r\nContent-Length: "+QByteArray::number(body.size())+"\r\nConnection: close\r\n\r\n"+body);
        s->disconnectFromHost();
    }
    void release(){auto list=pending;pending.clear();for(auto s:list)reply(s,201,"{\"conversation\":\"stale-conversation\"}");}
};
static bool waitFor(std::function<bool()> p) {
    QElapsedTimer t;t.start();while(!p()&&t.elapsed()<2500){QCoreApplication::processEvents();QThread::msleep(1);}return p();
}
static void drain(){QElapsedTimer t;t.start();while(t.elapsed()<120){QCoreApplication::processEvents();QThread::msleep(1);}}
class PendingStartRegression {
public:
    static int run(){
        int failures=0;
        auto check=[&](bool ok,const char *name){qInfo().noquote()<<(ok?"PASS":"FAIL")<<name;if(!ok)++failures;};
        for(const QString action:{"suspend","suspend-stay","cancel","reset","duplicate","happy","background","initial-background","existing","supersede"}) {
            QFile::remove(QStandardPaths::writableLocation(QStandardPaths::AppDataLocation)+"/settings.json");
            ControlledServer server;StubVoice v;drain();
            v.m_base="http://127.0.0.1:"+QString::number(server.serverPort());
            v.m_token=QString(48,'x');v.m_conversation.clear();v.m_turn.clear();v.m_ready=true;v.set("armed","test");
            // New lifecycle method absent on red baseline; invoke only if present.
            auto foreground=[&]{if(v.metaObject()->indexOfMethod("foregrounded()")>=0)QMetaObject::invokeMethod(&v,"foregrounded");drain();};
            if(action!="initial-background")foreground();
            if(action=="existing") {
                v.m_conversation="existing";v.primary();drain();
                check(v.captures==1&&server.creates==0,"existing conversation explicit tap captures without POST");
                check(v.findChildren<QAudioInput*>().isEmpty()&&!QFile::exists(v.storage()+"/capture.wav"),"existing conversation zero hardware capture");
                v.m_conversation.clear();v.save();continue;
            }
            if(action=="background")v.suspended();
            v.primary();
            if(action=="background"||action=="initial-background") {
                drain();check(server.creates==0&&v.captures==0,"background tap cannot create/capture");continue;
            }
            check(waitFor([&]{return server.creates==1;}),qPrintable(action+" request admitted"));
            if(action=="suspend") {v.suspended();foreground();}
            if(action=="suspend-stay")v.suspended();
            if(action=="cancel")v.cancel();
            if(action=="reset")v.newConversation();
            if(action=="duplicate") {v.primary();drain();check(server.creates==1,"duplicate tap single conversation POST");}
            if(action=="supersede") {
                v.cancel();v.reconnect();drain();v.primary();
                check(waitFor([&]{return server.creates==2;}),"fresh tap admits replacement");
                auto old=server.pending.takeFirst();ControlledServer::reply(old,201,"{\"conversation\":\"old\"}");drain();
                check(v.captures==0&&v.m_conversation.isEmpty(),"old epoch cannot consume new intent");
            }
            drain();const QString stateBefore=v.state(),textBefore=v.transcript();
            server.release();drain();
            bool cancelled=action=="suspend"||action=="suspend-stay"||action=="cancel"||action=="reset";
            if(cancelled){
                check(v.captures==0,qPrintable(action+" late201 no capture"));
                check(v.m_conversation.isEmpty(),qPrintable(action+" late201 no session mutation"));
                check(v.state()==stateBefore&&v.transcript()==textBefore,qPrintable(action+" late201 no UI mutation"));
                QFile settings(v.storage()+"/settings.json");
                bool persistedSafe=!settings.exists();
                if(settings.open(QIODevice::ReadOnly))persistedSafe=QJsonDocument::fromJson(settings.readAll()).object()["conversation"].toString().isEmpty();
                check(persistedSafe,qPrintable(action+" no persisted stale session"));
                if(action=="suspend-stay") {foreground();check(v.captures==0,"resume alone never captures");}
                v.reconnect();drain();v.primary();
                check(waitFor([&]{return !server.pending.isEmpty();}),qPrintable(action+" explicit fresh tap possible"));
                server.release();drain();check(v.captures==1,qPrintable(action+" fresh tap captures once"));
            } else check(v.captures==1,qPrintable(action+" explicit foreground capture once"));
            check(v.findChildren<QAudioInput*>().isEmpty(),"zero QAudioInput objects");
            check(!QFile::exists(v.storage()+"/capture.wav"),"no capture.wav");
            v.m_conversation.clear();v.save();
        }
        qInfo()<<"failures="<<failures;return failures?1:0;
    }
};
int main(int argc,char **argv){
    QTemporaryDir home;qputenv("XDG_DATA_HOME",home.path().toUtf8());
    QCoreApplication app(argc,argv);app.setApplicationName("r1-pending-start-regression");
    return PendingStartRegression::run();
}
