(function(){
  var el=document.getElementById('dash');if(!el)return;
  var rid=el.dataset.rid,uuid=el.dataset.uuid,domain=el.dataset.superset,box=document.getElementById('dash-state');
  function show(html){box.innerHTML=html}
  function err(t,m){box.replaceChildren();var d=document.createElement('div');d.className='empty';d.setAttribute('role','alert');var h=document.createElement('h2');h.textContent=t;var p=document.createElement('p');p.textContent=m;var b=document.createElement('button');b.className='btn';b.textContent='Try again';b.addEventListener('click',function(){location.reload()});d.append(h,p,b);box.appendChild(d)}
  async function fetchToken(){
    var r=await fetch('/api/reports/'+encodeURIComponent(rid)+'/guest-token',{credentials:'same-origin',cache:'no-store'});
    if(r.status===401){location.href='/signin?reason=expired';throw new Error('auth')}
    if(r.status===403){err('Permission denied','You no longer have access to this report.');throw new Error('denied')}
    if(!r.ok){var j={};try{j=await r.json()}catch(e){}err('Report unavailable',j.error||'The report service is unavailable.');throw new Error('unavailable')}
    return (await r.json()).token}
  window.mount({id:uuid,supersetDomain:domain,mountPoint:el,fetchGuestToken:fetchToken,dashboardUiConfig:{hideTitle:true,hideChartControls:true,hideTab:true,filters:{expanded:false}}})
    .then(function(){var s=document.getElementById('dash-skel');var t=setInterval(function(){if(el.querySelector('iframe')){clearInterval(t);setTimeout(function(){if(s)s.remove()},2500)}},300)})
    .catch(function(){});
})();
