const SH={
  pos(){return new Promise((res,rej)=>{if(!navigator.geolocation)return rej('no geo');
    navigator.geolocation.getCurrentPosition(p=>res({lat:p.coords.latitude,lng:p.coords.longitude}),rej,{enableHighAccuracy:true,timeout:10000})})},
  async post(url,body){const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});return r.json()},
  async alert(kind,message){let p={};try{p=await SH.pos()}catch(e){}return SH.post('/api/sos',{kind,message,...p})},
  async battery(el){if(!navigator.getBattery){el.textContent='Battery API not supported in this browser.';return}
    const b=await navigator.getBattery();let sent=false;
    const upd=()=>{const pct=Math.round(b.level*100);el.textContent=pct+'% '+(b.charging?'(charging)':'');
      if(pct<=15&&!b.charging&&!sent&&!sessionStorage.getItem('batAlert')){sent=true;sessionStorage.setItem('batAlert','1');
        if(confirm('Battery is at '+pct+'%. Send a low-battery alert with your location to your guardians?'))SH.alert('battery','Battery at '+pct+'%')}};
    b.addEventListener('levelchange',upd);b.addEventListener('chargingchange',upd);upd()}
};
