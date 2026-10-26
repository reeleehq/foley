// A tiny DOM, just enough to drive the panel page's script under node (no browser needed).
// Usage: node panel_page_shim.js <script.js>; prints one JSON object with what happened.
class El {
  constructor(tag){this.tag=tag;this.children=[];this.attrs={};this.dataset={};this.checked=false;this.value="";this.textContent="";}
  setAttribute(k,v){this.attrs[k]=String(v); if(k==="value")this.value=String(v); if(k.startsWith("data-")) this.dataset[k.slice(5)]=String(v);}
  append(...k){for(const c of k)this.children.push(typeof c==="string"?{text:c}:c);}
  replaceChildren(...k){this.children=[];this.append(...k);}
  walk(f){for(const c of this.children){ if(c instanceof El){f(c);c.walk(f);} }}
  querySelector(sel){return this.querySelectorAll(sel)[0];}
  querySelectorAll(sel){const out=[];this.walk(n=>{
    if(sel==="input[name=g]:checked"&&n.tag==="input"&&n.attrs.name==="g"&&n.checked)out.push(n);
    else if(sel==="input[name=c]:checked"&&n.tag==="input"&&n.attrs.name==="c"&&n.checked)out.push(n);
    else if(sel==="input[type=range]"&&n.tag==="input"&&n.attrs.type==="range")out.push(n);
  });return out;}
  findAll(tag){const o=[];this.walk(n=>{if(n.tag===tag)o.push(n)});return o;}
}
const app=new El("div"), who=new El("input"); who.value="ann";
global.document={getElementById:id=>id==="app"?app:who,createElement:t=>new El(t)};
global.localStorage={_d:{},getItem(k){return this._d[k]||null},setItem(k,v){this._d[k]=v}};
global.URL={createObjectURL:b=>{global.BLOB=b;return "blob:x"}}; global.Blob=class{constructor(p){this.parts=p}};
const fs=require("fs"); const src=fs.readFileSync(process.argv[2],"utf8");
// patch el(): the real script assigns on* handlers as properties; keep them
new Function("document","localStorage","URL","Blob",src+";globalThis.__api={show,start,get state(){return {at,answers,rater}},set rater(v){rater=v}};")(document,localStorage,URL,Blob);
const api=globalThis.__api;
const click=(root,pred)=>{let b;root.walk(n=>{if(!b&&n.tag==="button"&&pred(n))b=n});b.onclick();};
const text=n=>n.children.map(c=>c.text||"").join("");
const log={};
const startAs=name=>{who.value=name; click(app,n=>text(n)==="Start or continue");};
startAs("ann");
log.rater=api.state.rater;
click(app,n=>text(n)==="Next"); log.blockedWithoutAnswer=api.state.at===0;
app.walk(n=>{if(n.tag==="input"&&n.attrs.name==="g"&&n.attrs.value==="3")n.checked=true});
click(app,n=>text(n)==="Next");
const radios=app.findAll("input").filter(n=>n.attrs.name==="c"); radios[0].checked=true;
click(app,n=>text(n)==="Next");
click(app,n=>text(n)==="Next"); log.mushraBlockedUntouched=api.state.at===2;
let i=10; for(const r of app.findAll("input").filter(n=>n.attrs.type==="range")){r.value=String(i+=20); r.oninput();}
click(app,n=>text(n)==="Next");
log.doneAt=api.state.at;
let dl; app.walk(n=>{if(n.tag==="a")dl=n}); log.download=dl.attrs.download; log.responses=global.BLOB.parts[0];
// a second rater on the same browser starts clean; the first one resumes where they were
api.start(); startAs("bo"); log.secondRaterAt=api.state.at;
api.start(); startAs("ann"); log.firstRaterAt=api.state.at;
console.log(JSON.stringify(log));
