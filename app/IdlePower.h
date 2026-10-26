#pragma once
#include <QObject>
#include <QEvent>
#include <QMouseEvent>
#include <QGuiApplication>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QSaveFile>
#include <QFile>
#include <QDir>
#include <QStandardPaths>
#include <QUuid>
#include <QTimer>
#include <time.h>

// Fixed private-data journal, not a privileged command channel. No timer/heartbeat.
class IdlePower : public QObject {
    QString boot, session=QUuid::createUuid().toString(QUuid::Id128), operation;
    QJsonArray events;
    qint64 seq=0;
    QTimer inputFlush;
    double pendingInput=-1,lastInput=-1;
    static double now() {timespec ts;if(clock_gettime(CLOCK_BOOTTIME,&ts)!=0)return -1;return double(ts.tv_sec)+double(ts.tv_nsec)/1000000000.;}
public:
    explicit IdlePower(QObject *parent=nullptr):QObject(parent) {
        QFile f("/proc/sys/kernel/random/boot_id");
        if(f.open(QIODevice::ReadOnly))boot=QString::fromLatin1(f.readAll()).trimmed();
        inputFlush.setSingleShot(true);
        QObject::connect(&inputFlush,&QTimer::timeout,this,[this]{flushInput();});
    }
    void send(const QString &kind,const QString &op=QString(),double at=-1) {
        if(boot.isEmpty())return;
        if(at<0)at=now();if(at<0)return;
        events.append(QJsonObject{{"seq",double(++seq)},{"at",at},{"kind",kind},{"op",op}});
        while(events.size()>32)events.removeFirst();
        auto dir=QStandardPaths::writableLocation(QStandardPaths::AppDataLocation);
        QDir().mkpath(dir);
        QSaveFile file(dir+"/power-events.json");
        if(!file.open(QIODevice::WriteOnly))return;
        file.setPermissions(QFileDevice::ReadOwner|QFileDevice::WriteOwner);
        file.write(QJsonDocument(QJsonObject{{"boot",boot},{"session",session},{"events",events}}).toJson(QJsonDocument::Compact));
        file.commit();
    }
    void flushInput() {
        inputFlush.stop();
        if(pendingInput<0)return;
        lastInput=pendingInput;pendingInput=-1;send("input",QString(),lastInput);
    }
    void input(bool final=false) {
        pendingInput=now();
        if(final||lastInput<0||pendingInput-lastInput>=1)flushInput();
        else if(!inputFlush.isActive())inputFlush.start(250);
    }
    void begin() {
        flushInput();
        if(!operation.isEmpty())return;
        operation=QUuid::createUuid().toString(QUuid::Id128);send("begin",operation);
    }
    void finish(bool cancelled=false) {
        flushInput();
        if(operation.isEmpty())return;
        send(cancelled?"cancel":"end",operation);operation.clear();
    }
    bool eventFilter(QObject *,QEvent *e) override {
        // Automatic activation, timers, status, network and SSH never count.
        if(QGuiApplication::applicationState()!=Qt::ApplicationActive||!e->spontaneous())return false;
        bool input=false;
        switch(e->type()) {
        case QEvent::TouchBegin:case QEvent::TouchUpdate:case QEvent::TouchEnd:
        case QEvent::MouseButtonPress:case QEvent::MouseButtonRelease:
        case QEvent::KeyPress:case QEvent::KeyRelease:case QEvent::Wheel: input=true;break;
        case QEvent::MouseMove:input=static_cast<QMouseEvent*>(e)->buttons()!=Qt::NoButton;break;
        default:break;
        }
        if(input)this->input(e->type()==QEvent::TouchEnd||e->type()==QEvent::MouseButtonRelease||e->type()==QEvent::KeyRelease);
        return false; // observation only; never injects/replays mic or actions
    }
};
