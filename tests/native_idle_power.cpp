#include "IdlePower.h"
#include "AppIdentity.h"
#include <QCoreApplication>
#include <QThread>
#include <cassert>
#include <cstdio>
int main(int argc,char **argv){
 QCoreApplication app(argc,argv);initializeAppIdentity(app);
 auto path=QStandardPaths::writableLocation(QStandardPaths::AppDataLocation)+"/power-events.json";
 QFile::remove(path);IdlePower p;
 assert(!QFile::exists(path));
 p.input();p.begin();
 for(int n=0;n<1000;++n)p.input();
 p.finish(); // flush last actual input before end: same journal/session
 QFile f(path);assert(f.open(QIODevice::ReadOnly));auto bytes=f.readAll();f.close();
 auto o=QJsonDocument::fromJson(bytes).object();auto events=o["events"].toArray();
 assert(events.size()==4);
 assert(events[0].toObject()["kind"]=="input");
 assert(events[1].toObject()["kind"]=="begin");
 assert(events[2].toObject()["kind"]=="input");
 assert(events[3].toObject()["kind"]=="end");
 assert(events[1].toObject()["op"]==events[3].toObject()["op"]);
 QThread::msleep(350);app.processEvents();
 assert(f.open(QIODevice::ReadOnly));assert(f.readAll()==bytes);f.close();
 IdlePower restarted;app.processEvents();assert(f.open(QIODevice::ReadOnly));assert(f.readAll()==bytes);
 puts("PASS shared input/begin/end journal; 1000 updates coalesced; no background/startup writes");
}
