(function(){
  var root=document.documentElement;
  function setTheme(t){root.setAttribute('data-theme',t);try{localStorage.setItem('if-theme',t)}catch(e){}document.querySelectorAll('[data-theme-set]').forEach(function(b){b.setAttribute('aria-pressed',String(b.dataset.themeSet===t))})}
  document.querySelectorAll('[data-theme-set]').forEach(function(b){b.addEventListener('click',function(){setTheme(b.dataset.themeSet)})});
  var cur=root.getAttribute('data-theme');document.querySelectorAll('[data-theme-set]').forEach(function(b){b.setAttribute('aria-pressed',String(b.dataset.themeSet===cur))});
  var tt=document.getElementById('theme-toggle');if(tt)tt.addEventListener('click',function(){setTheme(root.getAttribute('data-theme')==='dark'?'light':'dark')});
  var sb=document.getElementById('sidebar'),ct=document.getElementById('collapse');
  try{if(localStorage.getItem('if-nav')==='collapsed'&&sb)sb.classList.add('collapsed')}catch(e){}
  if(ct&&sb)ct.addEventListener('click',function(){var c=sb.classList.toggle('collapsed');ct.setAttribute('aria-expanded',String(!c));try{localStorage.setItem('if-nav',c?'collapsed':'open')}catch(e){}});
  var nc=document.getElementById('navclose');function closeNav(){if(sb){sb.classList.remove('open')}var m=document.getElementById('navtoggle-m');if(m){m.setAttribute('aria-expanded','false');m.focus()}}if(nc)nc.addEventListener('click',closeNav);document.addEventListener('keydown',function(e){if(e.key==='Escape'&&sb&&sb.classList.contains('open'))closeNav()});
  var nm=document.getElementById('navtoggle-m');if(nm&&sb)nm.addEventListener('click',function(){var o=sb.classList.toggle('open');nm.setAttribute('aria-expanded',String(o))});
  var f=document.getElementById('report-filter');if(f)f.addEventListener('input',function(){var v=f.value.toLowerCase(),n=0;document.querySelectorAll('[data-report]').forEach(function(c){var m=c.dataset.report.indexOf(v)>-1;c.hidden=!m;if(m)n++});var e=document.getElementById('no-match');if(e)e.hidden=n>0});
  document.querySelectorAll('form[data-busy]').forEach(function(fm){fm.addEventListener('submit',function(){var b=fm.querySelector('button[type=submit]');if(b){b.disabled=true;b.textContent='Working…'}})});
  document.querySelectorAll('form[data-confirm]').forEach(function(fm){fm.addEventListener('submit',function(e){if(!confirm(fm.dataset.confirm))e.preventDefault()})});
})();
