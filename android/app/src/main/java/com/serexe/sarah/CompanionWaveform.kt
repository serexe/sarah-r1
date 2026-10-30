package com.serexe.sarah

import android.animation.ValueAnimator
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.fillMaxWidth

import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.repeatOnLifecycle
import kotlinx.coroutines.delay
import kotlin.math.PI
import kotlin.math.pow
import kotlin.math.sin

// Reserve both 152dp excursions plus the 9dp half-width of the widest glow stroke.
internal const val WAVEFORM_CANVAS_HEIGHT_DP=324f
/** Twice v34's visual displacement at every valid level; silence stays exactly flat. */
internal fun speakingWaveformHeightDp(level:Float):Float=level.coerceIn(0f,1f)*152f
// Preserve v35 gain when space permits; scale geometry, never audio, on short screens.
internal fun waveformRenderScale(heightDp:Float):Float=((heightDp/2f-9f)/152f).coerceIn(0f,1f)

/** Only presence animates. Status, transcript and Stop keep their own stationary layout. */
@Composable internal fun CompanionWaveform(phase:String,vm:SarahViewModel,modifier:Modifier=Modifier) {
 val lifecycle=LocalLifecycleOwner.current.lifecycle
 var tick by remember {mutableFloatStateOf(0f)}
 var amplitude by remember {mutableFloatStateOf(0f)}
 val speaking=phase=="playing"
 val listening=phase=="recording"
 val thinking=phase in setOf("polling","finalizing","uploading","reply_audio_pending","creating")
 LaunchedEffect(phase,lifecycle) {
  amplitude=0f;tick=0f
  try {
   lifecycle.repeatOnLifecycle(Lifecycle.State.STARTED) {
    try {
     while(speaking || listening || thinking) {
      val motion=ValueAnimator.areAnimatorsEnabled()
      // Speaking height comes only from decoded reply PCM at MediaPlayer position.
      val target=if(speaking) vm.playbackAmplitude() else 0f
      amplitude=if(motion) amplitude+(target-amplitude)*(if(target>amplitude) .5f else .22f) else target
      if(motion) tick+=.033f else tick=0f
      delay(if(motion) 33L else 150L)
     }
    } finally {amplitude=0f;vm.clearPlaybackMeter()}
   }
  } finally {amplitude=0f;vm.clearPlaybackMeter()}
 }
 Canvas(modifier.fillMaxWidth().clipToBounds().semantics {
  contentDescription=when {speaking->"Speaking voice waveform";listening->"Listening gentle pulse";thinking->"Thinking slow wave";else->"Ready settled wave"}
 }) {
  val gradient=Brush.horizontalGradient(listOf(Color(0x08b59be5),Color(0xffbf9ef1),Color(0xffeadbff),Color(0xffb59be5),Color(0x08b59be5)))
  val path=Path();val echo=Path()
  val geometryScale=waveformRenderScale(size.height/density)
  fun trace(p:Path,offset:Float) {
   for(i in 0..160) {
    val u=i/160f
    val taper=sin(PI*u).coerceAtLeast(0.0).pow(1.8).toFloat()
    val amount=when {speaking->speakingWaveformHeightDp(amplitude);listening->7f*(.82f+.18f*sin(tick*1.8f));thinking->13f;else->2.5f}
    val wave=when {
     speaking->.60*sin(u*PI*8-tick*3+offset)+.27*sin(u*PI*14+tick*4+offset)+.13*sin(u*PI*20-tick*5)
     thinking->sin(u*PI*4-tick*.8f+offset)
     else->sin(u*PI*6+offset)
    }
    val x=size.width*(.04f+.92f*u)
    val y=size.height/2+amount.dp.toPx()*geometryScale*taper*wave.toFloat()
    if(i==0) p.moveTo(x,y) else p.lineTo(x,y)
   }
  }
  trace(path,0f);trace(echo,.62f)
  drawCircle(Brush.radialGradient(listOf(Color(0x16b9a0ef),Color.Transparent)),radius=size.minDimension*.58f)
  drawPath(path,gradient,alpha=.045f,style=Stroke(18.dp.toPx(),cap=StrokeCap.Round))
  drawPath(path,gradient,alpha=.09f,style=Stroke(7.dp.toPx(),cap=StrokeCap.Round))
  drawPath(echo,gradient,alpha=.26f,style=Stroke(1.dp.toPx(),cap=StrokeCap.Round))
  drawPath(path,gradient,style=Stroke(2.dp.toPx(),cap=StrokeCap.Round))
 }
}
