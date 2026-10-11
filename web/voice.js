// shared by dashboard + phone. Fast neural male voice: replies are split into short chunks, the server streams audio while it is
// still generating, and the next chunk is prefetched so speech never stalls. Falls back to the browser voice if the server can't.
const Voice={on:true,q:[],busy:false,until:0,audio:new Audio(),
 speaking(){return this.busy||Date.now()<this.until},
 chunks(t){const parts=(t.replace(/\s+/g,' ').match(/[^.!?\n]+[.!?]*\s*/g)||[t]),out=[];let cur='';
  for(const p of parts){if((cur+p).length>150&&cur){out.push(cur.trim());cur=p}else cur+=p}if(cur.trim())out.push(cur.trim());return out},
 say(t){if(!this.on||!t)return;this.chunks(String(t)).forEach(c=>this.q.push(c));this.pump()},
 stop(){this.q=[];this.audio.pause();speechSynthesis.cancel()},
 url(t){return '/tts?text='+encodeURIComponent(t)},
 async pump(){if(this.busy||!this.q.length)return;this.busy=true;
  while(this.q.length){const t=this.q.shift();if(this.q[0])fetch(this.url(this.q[0])).catch(()=>{});   // prefetch next chunk
   try{await this.play(t)}catch(e){await this.fallback(t)}}
  this.busy=false;this.until=Date.now()+700},
 play(t){return new Promise((res,rej)=>{const a=this.audio;let done=false;const fin=ok=>{if(done)return;done=true;clearTimeout(tm);ok?res():rej()};
  const tm=setTimeout(()=>fin(a.currentTime>0),30000);a.onended=()=>fin(true);a.onerror=()=>fin(false);a.src=this.url(t);a.play().catch(()=>fin(false))})},
 fallback(t){return new Promise(res=>{if(!window.speechSynthesis)return res();const vs=speechSynthesis.getVoices().filter(v=>/^en/i.test(v.lang));
  const u=new SpeechSynthesisUtterance(t);const mv=vs.find(v=>/male|david|guy|mark|daniel|george|ryan|james|alex/i.test(v.name)&&!/female|zira|hazel|susan/i.test(v.name));
  u.voice=mv||null;u.pitch=mv?.85:.5;u.rate=1.05;
  u.onend=u.onerror=res;setTimeout(res,20000);speechSynthesis.speak(u)})}};
// continuous mic with visible errors, auto-restart, no deadlocks.
// Asks the engine for 5 alternative transcripts and prefers the one that contains the wake word, so a mishearing in the top guess doesn't kill the wake-up.
function startMic(onFinal,onMsg){const SR=window.SpeechRecognition||window.webkitSpeechRecognition;if(!SR){onMsg('Browser has no speech recognition. Use Chrome/Edge.');return null}
 const h={on:true,r:null,fails:0,last:'',lt:0,stop(){this.on=false;try{this.r.abort()}catch(_){}}};
 const note=m=>{const n=Date.now();if(m==h.last&&n-h.lt<60000)return;h.last=m;h.lt=n;onMsg(m)};
 const WAKE=/\b(ant[h]?on\w*|and ?ton|an ton|aunt on|sonofanton|s[ou]n+|san)\b/i;
 const go=()=>{if(!h.on)return;const r=h.r=new SR();r.continuous=true;r.interimResults=true;r.maxAlternatives=5;r.lang='en-US';
  r.onresult=e=>{h.fails=0;for(let i=e.resultIndex;i<e.results.length;i++){const res=e.results[i];let x=res[0].transcript;if(!res.isFinal){onMsg('… '+x);continue}
   for(let k=0;k<res.length;k++){if(WAKE.test(res[k].transcript)){x=res[k].transcript;break}}
   if(!Voice.speaking())onFinal(x.trim())}};
  r.onerror=e=>{if(e.error=='no-speech'||e.error=='aborted')return;if(e.error=='network'){h.fails++;note('Browser mic needs internet and looks offline - the PC microphone (offline) takes over by itself.');return}note('mic error: '+e.error);if(e.error=='not-allowed'||e.error=='service-not-allowed'){h.on=false;onMsg('Mic blocked. Allow the microphone for this site (lock icon in the address bar).')}};
  r.onend=()=>{if(h.on)setTimeout(go,Math.min(15000,250*Math.pow(2,h.fails)))};try{r.start()}catch(_){setTimeout(go,500)}};go();return h}
