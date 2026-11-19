# -*- coding: utf-8 -*-
"""生成整页 demo：离线快照 + 示例持仓 + v3 仓位运营，输出 docs/page_demo.html。

只写 docs/page_demo.html，不动 web/ 下的线上产物。
用法：
  python3 scripts/gen_page_demo.py
"""
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src'))

from etfquant import config, pipeline  # noqa: E402

OUT = os.path.join(ROOT, 'docs', 'page_demo.html')

DEMO_JS = """
<script>
(function(){
  var DEMO=[['510300',30000],['510500',12000],['588000',10000],['159915',8000]];
  var CASH=87000, tries=0;
  var BANNER=__BANNER__;
  function init(){
    tries++;
    if(!window.D||!D.legs){ if(tries<120) setTimeout(init,50); return; }
    var rows=[];
    DEMO.forEach(function(x){
      var l=legOf(x[0]); if(!l) return;
      var px=n(l.last)||1;
      rows.push({code:x[0],name:l.name,
        shares:Math.round(x[1]/px/100)*100,cost:px*0.97,
        category:l.category,settle:'T+1'});
    });
    if(!rows.length){ setTimeout(init,80); return; }
    applyHold({rows:rows,cash:CASH});
    document.querySelectorAll('.nav-i').forEach(function(e){ e.classList.remove('hide'); });
    try{ closeLock(); }catch(e){}
    try{ render(); }catch(e){}
    try{ nav('p5'); }catch(e){}
    var c=document.querySelector('.content');
    if(c&&!document.getElementById('demoBanner')){
      var d=document.createElement('div');
      d.id='demoBanner';
      d.setAttribute('style','margin:10px 22px 0;padding:8px 12px;border:1px solid #f0c36d;'
        +'background:#fff8e6;color:#7a5b00;font-size:12px');
      d.textContent=BANNER;
      c.insertBefore(d,c.firstChild);
    }
  }
  window.addEventListener('load',function(){ setTimeout(init,0); });
})();
</script>
"""


def main():
    tmp = tempfile.mkdtemp(prefix='etfdemo_')
    config.WEB = tmp
    r = pipeline.run(use_live=False, write_packet=False)
    html = open(r['html'], encoding='utf-8').read()

    banner = ('演示页面：离线快照 + 示例持仓，仅用于查看页面结构与 v3 仓位运营口径，'
              '不是真实数据，也不构成投资建议。')
    html = html.replace('</body>', DEMO_JS.replace(
        '__BANNER__', json.dumps(banner, ensure_ascii=False)) + '\n</body>')

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        f.write(html)
    print('已生成 %s（%.1f KB · 状态 %s · 标的 %d 只）'
          % (OUT, len(html.encode('utf-8')) / 1024, r['status'], r['legs']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
