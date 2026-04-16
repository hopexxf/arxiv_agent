/* 论文追踪报道 - 前端逻辑 */

// 全局数据
let allPapers = [];
let overflowList = [];
let favorites = JSON.parse(localStorage.getItem('favorites') || '[]');

// DOM 元素
const els = {
  dateMode: document.getElementById('dateMode'),
  startDate: document.getElementById('startDate'),
  endDate: document.getElementById('endDate'),
  keyword: document.getElementById('keyword'),
  favoriteOnly: document.getElementById('favoriteOnly'),
  applyBtn: document.getElementById('applyBtn'),
  resetBtn: document.getElementById('resetBtn'),
  quickRange: document.getElementById('quickRange'),
  summary: document.getElementById('summary'),
  cards: document.getElementById('cards'),
  overflowSection: document.getElementById('overflowSection'),
  overflowList: document.getElementById('overflowList'),
  metaText: document.getElementById('metaText'),
  genTime: document.getElementById('genTime'),
};

// 初始化
async function init() {
  try {
    const res = await fetch('papers_data.json');
    const data = await res.json();
    allPapers = data.papers || [];
    overflowList = data.overflow_list || [];
    
    // 更新元信息
    els.metaText.textContent = `共 ${data.count} 篇论文 · ${data.overflow_count} 篇溢出`;
    
    // 显示生成时间
    if (data.generated_at) {
      els.genTime.textContent = `数据生成时间: ${data.generated_at}`;
    }
    
    // 设置默认日期范围
    if (data.crawled_date_max) {
      els.endDate.value = data.crawled_date_max;
      const minDate = new Date(data.crawled_date_max);
      minDate.setDate(minDate.getDate() - 7);
      els.startDate.value = minDate.toISOString().split('T')[0];
    }
    
    // 初始渲染（applyFilters会调用renderOverflowList）
    applyFilters();
    
  } catch (err) {
    console.error('加载数据失败:', err);
    els.summary.innerHTML = '<p style="color:red">加载数据失败，请检查 papers_data.json 是否存在</p>';
  }
}

// 渲染论文卡片
function renderCards(papers) {
  els.cards.innerHTML = '';
  
  if (papers.length === 0) {
    els.summary.textContent = '没有找到匹配的论文';
    return;
  }
  
  els.summary.textContent = `显示 ${papers.length} 篇论文`;
  
  const tpl = document.getElementById('paperTpl');
  
  papers.forEach((p, idx) => {
    const card = tpl.content.cloneNode(true);
    
    // 编号
    card.querySelector('.pill').textContent = `#${idx + 1}`;
    
    // 标题链接
    const titleLink = card.querySelector('.title');
    titleLink.textContent = p.title;
    titleLink.href = p.arxiv_url || `https://arxiv.org/abs/${p.arxiv_id}`;
    
    // 收藏按钮
    const favBtn = card.querySelector('.favorite-btn');
    const isFav = favorites.includes(p.arxiv_id);
    favBtn.textContent = isFav ? '★ 已收藏' : '☆ 收藏';
    favBtn.classList.toggle('active', isFav);
    favBtn.onclick = () => toggleFavorite(p.arxiv_id, favBtn);
    
    // 元信息
    card.querySelector('.meta').textContent = 
      `${p.authors} · ${p.published_date} · ${p.crawled_date}`;
    
    // 分类标签
    const tagsDiv = card.querySelector('.tags');
    if (p.categories) {
      p.categories.split(',').forEach(cat => {
        const tag = document.createElement('span');
        tag.className = 'tag';
        tag.textContent = cat.trim();
        tagsDiv.appendChild(tag);
      });
    }
    
    // 单位
    const aff = card.querySelector('.affiliations');
    aff.textContent = p.affiliations || '（未识别）';
    
    // 中文摘要
    const summaryCn = card.querySelector('.summary-cn');
    if (p.summary_cn) {
      summaryCn.textContent = p.summary_cn;
    } else {
      summaryCn.innerHTML = '<em style="color:var(--muted)">（暂无中文摘要）</em>';
    }
    
    // 英文摘要
    card.querySelector('.abstract').textContent = p.abstract;
    
    els.cards.appendChild(card);
  });
}

// 渲染溢出列表
function renderOverflowList(keyword = '', startDate = '', endDate = '') {
  if (overflowList.length === 0) {
    els.overflowSection.style.display = 'none';
    return;
  }
  
  let filtered = overflowList;
  
  // 日期筛选（使用published_date）
  if (startDate || endDate) {
    filtered = filtered.filter(item => {
      const d = item.published_date || item.crawled_date || '';
      if (startDate && d < startDate) return false;
      if (endDate && d > endDate) return false;
      return true;
    });
  }
  
  // 关键词筛选
  if (keyword) {
    const kw = keyword.toLowerCase();
    filtered = filtered.filter(item => {
      const text = `${item.title} ${item.arxiv_id || ''} ${item.authors || ''} ${item.abstract || ''}`.toLowerCase();
      return text.includes(kw);
    });
  }
  
  if (filtered.length === 0) {
    els.overflowSection.style.display = 'none';
    return;
  }
  
  els.overflowSection.style.display = 'block';
  
  const totalCount = overflowList.length;
  const shownCount = filtered.length;
  els.overflowSection.querySelector('h2').textContent =
    shownCount < totalCount
      ? `更多论文（${shownCount}/${totalCount}）`
      : `更多论文（共 ${totalCount} 篇）`;
  
  els.overflowList.innerHTML = '';
  
  filtered.forEach(item => {
    // 统一使用可展开卡片模式
    renderOverflowCard(item);
  });
}

// 渲染溢出论文卡片（可展开）
function renderOverflowCard(item) {
  const card = document.createElement('div');
  card.className = 'overflow-card collapsed';
  
  // 卡片头部
  const header = document.createElement('div');
  header.className = 'overflow-card-header';
  
  const titleLink = document.createElement('a');
  titleLink.href = item.arxiv_url || item.url || `https://arxiv.org/abs/${item.arxiv_id || ''}`;
  titleLink.target = '_blank';
  titleLink.rel = 'noopener';
  titleLink.className = 'overflow-title';
  titleLink.textContent = item.title;
  
  const toggleBtn = document.createElement('button');
  toggleBtn.className = 'overflow-toggle';
  toggleBtn.textContent = '展开';
  toggleBtn.onclick = () => {
    card.classList.toggle('collapsed');
    card.classList.toggle('expanded');
    toggleBtn.textContent = card.classList.contains('expanded') ? '收起' : '展开';
  };
  
  const dateSpan = document.createElement('span');
  dateSpan.className = 'date';
  dateSpan.textContent = item.published_date || item.crawled_date || '';
  
  header.appendChild(titleLink);
  header.appendChild(toggleBtn);
  header.appendChild(dateSpan);
  
  // 卡片内容（折叠）
  const content = document.createElement('div');
  content.className = 'overflow-card-content';
  
  // 作者和分类
  if (item.authors) {
    const meta = document.createElement('div');
    meta.className = 'overflow-meta';
    meta.textContent = item.categories ? `${item.authors} · ${item.categories}` : item.authors;
    content.appendChild(meta);
  }
  
  // 单位
  if (item.affiliations) {
    const aff = document.createElement('div');
    aff.className = 'overflow-affiliations';
    aff.textContent = `单位: ${item.affiliations}`;
    content.appendChild(aff);
  }
  
  // 中文摘要或英文摘要
  if (item.summary_cn) {
    const cnDiv = document.createElement('div');
    cnDiv.className = 'overflow-summary-cn';
    cnDiv.textContent = item.summary_cn;
    content.appendChild(cnDiv);
  } else if (item.abstract) {
    const absDiv = document.createElement('div');
    absDiv.className = 'overflow-abstract';
    absDiv.textContent = item.abstract;
    content.appendChild(absDiv);
  }
  
  card.appendChild(header);
  card.appendChild(content);
  els.overflowList.appendChild(card);
}

// 收藏切换
function toggleFavorite(arxivId, btn) {
  const idx = favorites.indexOf(arxivId);
  if (idx > -1) {
    favorites.splice(idx, 1);
    btn.textContent = '☆ 收藏';
    btn.classList.remove('active');
  } else {
    favorites.push(arxivId);
    btn.textContent = '★ 已收藏';
    btn.classList.add('active');
  }
  localStorage.setItem('favorites', JSON.stringify(favorites));
}

// 应用筛选
function applyFilters() {
  const dateMode = els.dateMode.value;
  const startDate = els.startDate.value;
  const endDate = els.endDate.value;
  const keyword = els.keyword.value.toLowerCase().trim();
  const favOnly = els.favoriteOnly.checked;
  
  let filtered = allPapers.filter(p => {
    // 日期筛选
    if (startDate || endDate) {
      const date = p[dateMode];
      if (startDate && date < startDate) return false;
      if (endDate && date > endDate) return false;
    }
    
    // 收藏筛选
    if (favOnly && !favorites.includes(p.arxiv_id)) {
      return false;
    }
    
    // 关键词筛选
    if (keyword) {
      const searchText = `${p.title} ${p.authors} ${p.affiliations} ${p.abstract} ${p.summary_cn}`.toLowerCase();
      if (!searchText.includes(keyword)) return false;
    }
    
    return true;
  });
  
  renderCards(filtered);
  renderOverflowList(keyword, startDate, endDate);
}

// 重置筛选
function resetFilters() {
  els.keyword.value = '';
  els.favoriteOnly.checked = false;
  
  // 重置日期为最近7天
  if (allPapers.length > 0) {
    const maxDate = allPapers[0].crawled_date;
    els.endDate.value = maxDate;
    const minDate = new Date(maxDate);
    minDate.setDate(minDate.getDate() - 7);
    els.startDate.value = minDate.toISOString().split('T')[0];
  }
  
  applyFilters();
}

// 快捷日期范围
function setQuickRange(range) {
  const today = new Date();
  let start = new Date();
  
  switch(range) {
    case 'today':
      start = today;
      break;
    case '3d':
      start.setDate(today.getDate() - 3);
      break;
    case '7d':
      start.setDate(today.getDate() - 7);
      break;
    case 'all':
      els.startDate.value = '';
      els.endDate.value = '';
      applyFilters();
      return;
  }
  
  els.startDate.value = start.toISOString().split('T')[0];
  els.endDate.value = today.toISOString().split('T')[0];
  applyFilters();
}

// 事件绑定
els.applyBtn.addEventListener('click', applyFilters);
els.resetBtn.addEventListener('click', resetFilters);
els.keyword.addEventListener('keypress', e => {
  if (e.key === 'Enter') applyFilters();
});

els.quickRange.addEventListener('click', e => {
  if (e.target.dataset.range) {
    setQuickRange(e.target.dataset.range);
  }
});

// 启动
init();
