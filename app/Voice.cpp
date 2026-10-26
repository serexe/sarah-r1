#include "Voice.h"
#include <QAudioDeviceInfo>
#include <QNetworkReply>
#include <QNetworkRequest>
#include <QJsonDocument>
#include <QJsonObject>
#include <QStandardPaths>
#include <QSaveFile>
#include <QDir>
#include <QUuid>
#include <QtEndian>
#include <QUrl>
#include <QSslConfiguration>
#include <QSslCertificate>
#include <QSslSocket>
#include <cstring>

// Sequential one-shot body: Qt cannot rewind/replay accepted audio after lost response.
class OneShotUpload:public QIODevice {
    QByteArray bytes; qint64 offset=0;
public:
    explicit OneShotUpload(QByteArray data):bytes(data){open(QIODevice::ReadOnly);}
    bool isSequential()const override{return true;}
    qint64 bytesAvailable()const override{return bytes.size()-offset+QIODevice::bytesAvailable();}
    qint64 readData(char *out,qint64 max)override{auto n=qMin(max,qint64(bytes.size())-offset);if(n<=0)return -1;memcpy(out,bytes.constData()+offset,n);offset+=n;return n;}
    qint64 writeData(const char*,qint64)override{return -1;}
};

Voice::Voice(QObject *parent):QObject(parent){
    QDir().mkpath(storage());
    QFile f(storage()+"/settings.json");
    if(f.open(QIODevice::ReadOnly)){
        auto o=QJsonDocument::fromJson(f.readAll()).object();m_base=o["base"].toString();m_token=o["token"].toString();
        m_conversation=o["conversation"].toString();m_turn=o["turn"].toString();m_request=o["request"].toString();m_transcript=o["transcript"].toString();m_cancelPending=o["cancel_pending"].toBool();
    }
    m_clip.setFileName(storage()+"/capture.wav");QFile::remove(m_clip.fileName()); // abandoned capture never auto-sent
    m_limit.setSingleShot(true);connect(&m_limit,&QTimer::timeout,this,[this]{if(m_recording||m_input)cancel();});
    m_poll.setInterval(1500);connect(&m_poll,&QTimer::timeout,this,&Voice::poll);
    connect(&m_player,&QMediaPlayer::mediaStatusChanged,this,[this](QMediaPlayer::MediaStatus status){if(status==QMediaPlayer::EndOfMedia&&m_audioActive){m_audioActive=false;set("ready","Tap once. No holding.");}});
    QTimer::singleShot(0,this,&Voice::reconnect);
}
QString Voice::storage()const{return QStandardPaths::writableLocation(QStandardPaths::AppDataLocation);}
void Voice::set(QString s,QString d){m_state=s;m_detail=d;if(s=="error"||s=="offline"||s=="ready"||s=="confirming"||(s=="armed"&&!m_audioActive))m_power.finish();emit changed();}
bool Voice::save(){
    QSaveFile f(storage()+"/settings.json");if(!f.open(QIODevice::WriteOnly))return false;
    f.setPermissions(QFileDevice::ReadOwner|QFileDevice::WriteOwner);
    f.write(QJsonDocument(QJsonObject{{"base",m_base},{"token",m_token},{"conversation",m_conversation},{"turn",m_turn},{"request",m_request},{"transcript",m_transcript},{"cancel_pending",m_cancelPending}}).toJson());return f.commit();
}
void Voice::configure(QString url,QString token){
    QUrl u(url);if(u.scheme()!="https"||u.host().isEmpty()||!u.userInfo().isEmpty()||u.hasQuery()||u.hasFragment()||(u.path()!=""&&u.path()!="/")||token.size()<40){set("error","Use HTTPS origin and device token (40+ characters)");return;}
    cancel();++m_epoch;m_base=url;while(m_base.endsWith('/'))m_base.chop(1);m_token=token;m_conversation.clear();m_turn.clear();m_request.clear();m_cancelPending=false;m_transcript.clear();save();reconnect();
}
void Voice::request(QString method,QString path,QByteArray data,std::function<void(QByteArray,int)> done,QByteArray type){
    QNetworkRequest req(QUrl(m_base+path));req.setRawHeader("Authorization","Bearer "+m_token.toUtf8());req.setHeader(QNetworkRequest::ContentTypeHeader,type);
    // Optional coordinator-provisioned private CA; normal peer/hostname verification stays enabled.
    QFile ca(storage()+"/server-ca.pem");if(ca.open(QIODevice::ReadOnly)&&ca.size()<=16384){auto certificates=QSslCertificate::fromData(ca.readAll());if(!certificates.isEmpty()){auto tls=QSslConfiguration::defaultConfiguration();tls.addCaCertificates(certificates);tls.setPeerVerifyMode(QSslSocket::VerifyPeer);req.setSslConfiguration(tls);}}
    req.setAttribute(QNetworkRequest::RedirectPolicyAttribute,QNetworkRequest::ManualRedirectPolicy);req.setTransferTimeout(15000);
    if(path=="/v1/turns"){req.setRawHeader("X-Conversation",m_conversation.toUtf8());req.setRawHeader("Idempotency-Key",m_request.toUtf8());}
    QNetworkReply *reply;
    if(method=="POST"&&(path=="/v1/turns"||path.endsWith("/confirmation"))){
        auto body=new OneShotUpload(data);req.setAttribute(QNetworkRequest::DoNotBufferUploadDataAttribute,true);req.setHeader(QNetworkRequest::ContentLengthHeader,data.size());
        reply=m_net.sendCustomRequest(req,method.toLatin1(),body);body->setParent(reply);
    }else reply=m_net.sendCustomRequest(req,method.toLatin1(),data);
    int epoch=m_epoch;
    connect(reply,&QNetworkReply::finished,this,[this,reply,done,epoch]{int code=reply->attribute(QNetworkRequest::HttpStatusCodeAttribute).toInt();auto bytes=reply->readAll();reply->deleteLater();if(epoch==m_epoch)done(bytes,code);});
    // Qt validates TLS by default. Never ignoreSslErrors or follow redirected credentials.
}
void Voice::reconnect(){
    if(!configured()){set("offline","Set up secure companion");return;}
    const int owner=m_owner,serial=++m_healthSerial;
    request("GET","/v1/health",{},[this,owner,serial](QByteArray b,int code){
        if(serial!=m_healthSerial||owner!=m_owner)return;
        auto o=QJsonDocument::fromJson(b).object();m_connected=code==200&&o["connected"].toBool();m_ready=m_connected&&o["ready"].toBool();
        if(m_recording||m_input||m_startPending||m_audioActive)return;
        if(!m_connected){set("offline","Connection unavailable. Tap Reconnect.");return;}
        // Reconciliation remains available even when provider is not ready.
        if(!m_turn.isEmpty()){if(m_cancelPending)cancelTurn();else{m_poll.start();poll();}return;}
        if(!m_request.isEmpty()){reconcile();return;}
        if(!m_ready){set("error",o["reason"].toString("Secure agent unavailable"));return;}
        set("armed","Connected. Tap to check microphone and talk.");
    });
}
void Voice::primary(){
    if(!m_foreground||m_startPending)return;
    if(m_recording||m_input){if(m_state=="listening")send();return;}
    if(!m_request.isEmpty()||!m_turn.isEmpty())return;
    if(m_audioActive){++m_epoch;m_audioActive=false;m_player.stop();set("armed","Audio stopped. Written reply kept.");return;}
    if(m_state=="listening"){send();return;}
    if((m_state=="armed"||m_state=="ready")&&m_ready){
        ++m_owner;m_power.begin();m_startPending=true;m_captureIntent=true;int epoch=m_epoch;
        set("starting","Preparing conversation · Cancel discards");
        if(m_conversation.isEmpty())request("POST","/v1/conversations","{}",[this,epoch](QByteArray b,int c){
            // Check live intent before any session mutation, not just before audio.
            if(epoch!=m_epoch||!m_foreground||!m_startPending||!m_captureIntent)return;
            QString conversation=QJsonDocument::fromJson(b).object()["conversation"].toString();
            if(c!=201||conversation.isEmpty()){m_startPending=false;m_captureIntent=false;set("error","Cannot create conversation");return;}
            m_conversation=conversation;save();captureIfWanted(epoch);
        });
        else captureIfWanted(epoch);
    }
}
void Voice::captureIfWanted(int epoch){
    if(epoch!=m_epoch||!m_foreground||!m_startPending||!m_captureIntent)return;
    m_startPending=false;m_captureIntent=false; // one explicit tap, at most one capture
    if(!m_ready){set("error","Secure agent unavailable");return;}
    if(m_recording||m_input)return;
    m_recording=true;m_limit.start(30000);startCapture();
}
void Voice::startCapture(){
    if(m_input)return;
    auto device=QAudioDeviceInfo::defaultInputDevice();QAudioFormat f;f.setCodec("audio/pcm");f.setSampleRate(16000);f.setChannelCount(1);f.setSampleSize(16);f.setSampleType(QAudioFormat::SignedInt);f.setByteOrder(QAudioFormat::LittleEndian);
    if(!device.isFormatSupported(f)){f=device.nearestFormat(f);}
    if(device.isNull()||f.sampleSize()!=16||f.sampleType()!=QAudioFormat::SignedInt||f.byteOrder()!=QAudioFormat::LittleEndian||(f.channelCount()!=1&&f.channelCount()!=2)||(f.sampleRate()!=16000&&f.sampleRate()!=44100&&f.sampleRate()!=48000)){discard();set("error","Supported microphone unavailable");return;}
    if(!m_clip.open(QIODevice::WriteOnly|QIODevice::Truncate)){discard();set("error","Private recording storage unavailable");return;}m_clip.setPermissions(QFileDevice::ReadOwner|QFileDevice::WriteOwner);m_clip.write(QByteArray(44,'\0'));
    m_input=new QAudioInput(device,f,this);connect(m_input,&QAudioInput::stateChanged,this,[this](QAudio::State s){if(!m_input)return;if(s==QAudio::StoppedState&&m_input->error()!=QAudio::NoError){discard();set("error","Microphone denied or unavailable");}});
    m_input->start(&m_clip);if(m_input&&m_input->error()==QAudio::NoError){m_elapsed.start();m_limit.start(30000);set("listening","Recording · max 30 seconds · Cancel discards");}else{discard();set("error","Microphone unavailable");}
}
void Voice::discard(){m_recording=false;m_limit.stop();if(m_input){auto p=m_input;m_input=nullptr;p->stop();p->deleteLater();}m_clip.close();QFile::remove(m_clip.fileName());}
void Voice::send(){
    if(!m_input)return;m_recording=false;auto f=m_input->format();auto p=m_input;m_input=nullptr;p->stop();p->deleteLater();m_limit.stop();
    qint64 count=m_clip.size()-44;
    if(count< f.sampleRate()*f.channelCount()*2/4){discard();set("error","Clip too short. Try again.");return;}
    QByteArray h;auto put16=[&](quint16 v){v=qToLittleEndian(v);h.append((char*)&v,2);};auto put32=[&](quint32 v){v=qToLittleEndian(v);h.append((char*)&v,4);};
    h.append("RIFF",4);put32(count+36);h.append("WAVEfmt ",8);put32(16);put16(1);put16(f.channelCount());put32(f.sampleRate());put32(f.sampleRate()*f.channelCount()*2);put16(f.channelCount()*2);put16(16);h.append("data",4);put32(count);
    m_clip.seek(0);m_clip.write(h);m_clip.close();QFile read(m_clip.fileName());read.open(QIODevice::ReadOnly);auto data=read.readAll();read.close();QFile::remove(m_clip.fileName());
    submitClip(data);
}
void Voice::submitClip(QByteArray data){
    ++m_owner;m_cancelPending=false;
    m_request=QUuid::createUuid().toString(QUuid::WithoutBraces);
    if(!save()){m_request.clear();set("error","Cannot persist request identity. Nothing sent.");return;}
    set("transcribing","No microphone capture");
    const auto key=m_request;const int owner=m_owner;
    request("POST","/v1/turns",data,[this,key,owner](QByteArray b,int c){
        if(key!=m_request||owner!=m_owner)return;
        auto o=QJsonDocument::fromJson(b).object();
        if(c!=202||o["turn"].toString().isEmpty()){
            // Unknown outcomes retain identity; never replay audio.
            if(c>=400&&c<500){m_request.clear();save();}
            set("error",c==0?"Upload outcome unknown. Reconnect; no automatic retry.":o["error"].toString("Request outcome unknown. Reconnect."));return;
        }
        m_turn=o["turn"].toString();save();m_poll.start();poll();
    },"audio/wav");
}
void Voice::reconcile(){
    if(m_request.isEmpty()||m_lookupPending)return;
    m_lookupPending=true;const auto key=m_request,conversation=m_conversation;const int owner=m_owner;
    set("reconnecting","Reconciling accepted request. No audio resubmission.");
    request("GET","/v1/requests/"+key,{},[this,key,conversation,owner](QByteArray b,int c){
        if(owner!=m_owner||key!=m_request)return;m_lookupPending=false;
        auto o=QJsonDocument::fromJson(b).object();
        if(c!=200||o["conversation"].toString()!=conversation||o["id"].toString().isEmpty()){
            set("error","Request outcome unresolved. Reconnect or explicitly start new conversation. No resubmission.");return;
        }
        m_turn=o["id"].toString();save();
        if(m_cancelPending)cancelTurn();else{m_poll.start();poll();}
    });
}
void Voice::poll(){
    if(m_turn.isEmpty()||m_pollPending||m_cancelPending)return;
    m_pollPending=true;const auto turn=m_turn;const int owner=m_owner,serial=++m_pollSerial;
    request("GET","/v1/turns/"+turn,{},[this,turn,owner,serial](QByteArray b,int c){
        if(serial!=m_pollSerial)return;m_pollPending=false;
        if(owner!=m_owner||turn!=m_turn)return;
        if(c!=200){m_poll.stop();set("offline","Status unavailable. Reconnect; no resubmission.");return;}
        auto o=QJsonDocument::fromJson(b).object();QString s=o["state"].toString(),d=o["detail"].toString();
        if(s!="done"&&s!="error"&&s!="cancelled"&&s!="uncertain"){
            m_confirmation=s=="confirming"?o["confirmation"].toObject():QJsonObject();
            if(s=="confirming"&&m_confirmation["nonce"].toString()==m_confirmationSent){m_confirmation=QJsonObject();set("acting","Confirmation already sent once. Checking outcome.");return;}
            if(s=="confirming")d=m_confirmation["label"].toString()+" · confirm once or deny";
            set(s=="speaking"?"preparing":s,d);return;}
        m_confirmation=QJsonObject();
        m_poll.stop();if(!o["transcript"].toString().isEmpty())m_transcript+="YOU\n"+o["transcript"].toString()+"\n\n";
        m_transcript+="S.A.R.A.H\n"+d+"\n\n";m_turn.clear();m_request.clear();m_cancelPending=false;save();
        m_audioActive=s=="done"&&o["audio"].toBool()&&m_foreground;
        set(s=="done"?"armed":"error",d);
        if(m_audioActive){
            set("speaking","Fetching spoken reply · tap to stop");
            request("GET","/v1/turns/"+turn+"/audio",{},[this,owner](QByteArray bytes,int code){
                if(owner!=m_owner||!m_audioActive||!m_foreground)return;
                if(code!=200){m_audioActive=false;set("armed","Audio unavailable. Written reply kept.");return;}
                QString path=storage()+"/reply.mp3";QSaveFile out(path);
                if(!out.open(QIODevice::WriteOnly)){m_audioActive=false;set("armed","Audio storage unavailable. Written reply kept.");return;}
                out.setPermissions(QFileDevice::ReadOwner|QFileDevice::WriteOwner);out.write(bytes);
                if(!out.commit()){m_audioActive=false;set("armed","Audio storage unavailable. Written reply kept.");return;}
                set("speaking","Playing reply · tap to stop");playReply(path);
            });
        }
    });
}
void Voice::playReply(const QString &path){m_player.setMedia(QUrl::fromLocalFile(path));m_player.play();}
void Voice::confirmAction(bool accept){
    if(!m_foreground||m_state!="confirming"||m_turn.isEmpty()||m_confirmation.isEmpty())return;
    auto value=m_confirmation;m_confirmation=QJsonObject();
    if(value["conversation"].toString()!=m_conversation)return;
    m_power.begin();
    m_confirmationSent=value["nonce"].toString();
    QJsonObject payload{{"conversation",m_conversation},{"nonce",value["nonce"]},{"action_hash",value["action_hash"]},{"accept",accept}};
    const auto turn=m_turn;const int owner=m_owner;
    set("acting","Confirmation sent once. Reconnect checks status; never resends approval.");
    request("POST","/v1/turns/"+turn+"/confirmation",QJsonDocument(payload).toJson(),[this,turn,owner](QByteArray,int){if(owner==m_owner&&turn==m_turn){m_poll.start();poll();}});
}
void Voice::cancelTurn(){
    const auto turn=m_turn;const int owner=m_owner;
    if(turn.isEmpty())return;
    request("POST","/v1/turns/"+turn+"/cancel","{}",[this,turn,owner](QByteArray,int c){
        if(owner!=m_owner||turn!=m_turn)return;
        if(c==200){m_turn.clear();m_request.clear();m_cancelPending=false;save();}
        set("error",c==200?"Cancelled locally. Does not undo actions; worker may still be cleaning up.":"Cancellation unconfirmed. Reconnect to reconcile.");
    });
}
void Voice::cancel(){
    m_power.finish(true);
    m_confirmation=QJsonObject();
    ++m_epoch;++m_owner;++m_pollSerial;m_pollPending=false;m_lookupPending=false;m_startPending=false;m_captureIntent=false;
    if(m_state=="starting")set("armed","Start cancelled. Tap to talk.");
    if(m_audioActive){m_audioActive=false;set("armed","Audio stopped. Written reply kept.");}
    m_player.stop();m_poll.stop();
    if(m_recording||m_input){discard();set("armed","Recording discarded. Nothing sent.");return;}
    if(!m_turn.isEmpty()||!m_request.isEmpty()){
        m_cancelPending=true;save();if(!m_turn.isEmpty())cancelTurn();else reconcile();
    }
}
void Voice::newConversation(){cancel();++m_epoch;++m_owner;m_lookupPending=false;m_pollPending=false;m_cancelPending=false;m_conversation.clear();m_turn.clear();m_request.clear();m_transcript.clear();save();reconnect();}
void Voice::suspended(){
    m_confirmation=QJsonObject();
    m_foreground=false;++m_epoch;++m_owner;++m_pollSerial;m_pollPending=false;m_lookupPending=false;m_startPending=false;m_captureIntent=false;
    if(m_recording||m_input){discard();set("armed","Recording discarded on suspension. Nothing sent.");}
    else if(m_state=="starting")set("armed","Start discarded on suspension. Tap to talk.");
    if(m_audioActive){m_audioActive=false;set("armed","Audio discarded on suspension. Written reply kept.");}
    m_player.stop();m_poll.stop();
}
void Voice::foregrounded(){m_foreground=true;reconnect();}
