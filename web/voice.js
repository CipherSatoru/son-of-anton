// shared by dashboard + phone: neural male voice via server /tts, browser voice fallback, mic gating that can't get stuck
const Voice={on:true,q:[],busy:false,until:0,audio:new Audio(),
 speaking(){return this.busy||Date.now()<this.until},
 say(t){if(!this.on||!t)return;this.q.push(t);this.pump()},
 stop(){this.q=[];this.audio.pause();speechSynthesis.cancel()},
 async pump(){if(this.busy||!this.q.length)return;this.busy=true;const t=this.q.shift();
  try{const r=await fetch('/tts?text='+encodeURIComponent(t));if(!r.ok)throw 0;this.audio.src=URL.createObjectURL(await r.blob());await this.audio.play();
   await new Promise(res=>{this.audio.onended=res;this.audio.onerror=res;setTimeout(res,30000)})}
  catch(e){await this.fallback(t)}
  this.busy=false;this.until=Date.now()+700;this.pump()},
 fallback(t){return new Promise(res=>{if(!window.speechSynthesis)return res();const vs=speechSynthesis.getVoices().filter(v=>/^en/i.test(v.lang));
  const u=new SpeechSynthesisUtterance(t);u.voice=vs.find(v=>/male|david|guy|mark|daniel|george|ryan|james|alex/i.test(v.name)&&!/female|zira|hazel|susan/i.test(v.name))||null;u.pitch=.8;u.rate=1.05;
  u.onend=u.onerror=res;setTimeout(res,20000);speechSynthesis.speak(u)})}};
// continuous mic with visible errors, auto-restart, no deadlocks
function startMic(onFinal,onMsg){const SR=window.SpeechRecognition||window.webkitSpeechRecognition;if(!SR){onMsg('Browser has no speech recognition. Use Chrome/Edge.');return null}
 const h={on:true,r:null,stop(){this.on=false;try{this.r.abort()}catch(_){}}};
 const go=()=>{if(!h.on)return;const r=h.r=new SR();r.continuous=true;r.interimResults=true;r.lang='en-US';
  r.onresult=e=>{for(let i=e.resultIndex;i<e.results.length;i++){const x=e.results[i][0].transcript;if(!e.results[i].isFinal){onMsg('… '+x);continue}if(!Voice.speaking())onFinal(x.trim())}};
  r.onerror=e=>{onMsg('mic error: '+e.error);if(e.error=='not-allowed'||e.error=='service-not-allowed'){h.on=false;onMsg('Mic blocked. Allow the microphone for this site (lock icon in the address bar).')}};
  r.onend=()=>{if(h.on)setTimeout(go,250)};try{r.start()}catch(_){setTimeout(go,500)}};go();return h}
