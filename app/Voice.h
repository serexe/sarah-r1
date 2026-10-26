#pragma once
#include <QObject>
#include <QAudioInput>
#include <QFile>
#include <QNetworkAccessManager>
#include <QMediaPlayer>
#include <QTimer>
#include <QElapsedTimer>
#include <QJsonObject>
#include "IdlePower.h"

class Voice : public QObject {
    Q_OBJECT
    Q_PROPERTY(QString state READ state NOTIFY changed)
    Q_PROPERTY(QString detail READ detail NOTIFY changed)
    Q_PROPERTY(QString transcript READ transcript NOTIFY changed)
    Q_PROPERTY(bool connected READ connected NOTIFY changed)
    Q_PROPERTY(bool configured READ configured NOTIFY changed)
public:
    IdlePower *powerActivity(){return &m_power;}
    explicit Voice(QObject *parent=nullptr);
    QString state() const{return m_state;}
    QString detail() const{return m_detail;}
    QString transcript() const{return m_transcript;}
    bool connected() const{return m_connected;}
    bool configured() const{return !m_base.isEmpty()&&!m_token.isEmpty();}
    Q_INVOKABLE void configure(QString url,QString token);
    Q_INVOKABLE void reconnect();
    Q_INVOKABLE void primary();
    Q_INVOKABLE void cancel();
    Q_INVOKABLE void newConversation();
    Q_INVOKABLE void suspended();
    Q_INVOKABLE void foregrounded();
    Q_INVOKABLE void confirmAction(bool accept);
signals:
    void changed();
protected:
    // Native regression overrides the hardware boundary; production uses Qt audio.
    virtual void startCapture();
    virtual void playReply(const QString &path);
private:
    friend class PendingStartRegression;
    QString m_state="offline",m_detail="Set up secure companion",m_transcript,m_base,m_token,m_conversation,m_turn,m_request;
    IdlePower m_power;
    bool m_connected=false,m_ready=false;
    bool m_foreground=false,m_startPending=false,m_captureIntent=false;
    bool m_recording=false,m_pollPending=false,m_lookupPending=false,m_cancelPending=false;
    bool m_audioActive=false; // Local fetch/playback only; never server TTS preparation.
    int m_owner=0,m_healthSerial=0,m_pollSerial=0;
    QAudioInput *m_input=nullptr;
    QFile m_clip;
    QNetworkAccessManager m_net;
    QMediaPlayer m_player;
    QTimer m_poll,m_limit;
    QElapsedTimer m_elapsed;
    int m_epoch=0;
    QJsonObject m_confirmation;
    QString m_confirmationSent;
    void set(QString state,QString detail);
    QString storage() const;
    bool save();
    void discard();
    void captureIfWanted(int epoch);
    void send();
    void submitClip(QByteArray data);
    void poll();
    void reconcile();
    void cancelTurn();
    void request(QString method,QString path,QByteArray data,std::function<void(QByteArray,int)> done,QByteArray type="application/json");
};
