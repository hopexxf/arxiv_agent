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
  sortBy: document.getElementById('sortBy'),
  sortDirBtn: document.getElementById('sortDirBtn'),
  summary: document.getElementById('summary'),
  cards: document.getElementById('cards'),
  overflowSection: document.getElementById('overflowSection'),
  overflowList: document.getElementById('overflowList'),
  metaText: document.getElementById('metaText'),
  genTime: document.getElementById('genTime'),
  qualityMin: document.getElementById('qualityMin'),
  qualityMinLabel: document.getElementById('qualityMinLabel'),
};

// 排序状态
let sortBy = 'relevance';   // 'relevance' | 'published_date' | 'crawled_date' | 'title'
let sortDir = 'desc';       // 'asc' | 'desc'

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

    // 质量评分徽章
    const qa = p.quality_assessment;
    if (qa && qa.overall_score !== undefined) {
      const score = qa.overall_score;
      let level, label;
      if (score >= 80) { level = 'excellent'; label = '★★★★★'; }
      else if (score >= 65) { level = 'good';    label = '★★★★'; }
      else if (score >= 50) { level = 'fair';    label = '★★★'; }
      else                   { level = 'poor';   label = '★★'; }

      const badge = document.createElement('span');
      badge.className = `quality-badge ${level}`;
      badge.title = `质量分数: ${score}/100 · ${level}`;
      badge.innerHTML = `<span class="score">${score}</span><span>${label}</span>`;
      tagsDiv.appendChild(badge);
    } else {
      // 无质量评估数据
      const badge = document.createElement('span');
      badge.className = 'quality-badge unknown';
      badge.textContent = '（未评估）';
      badge.title = '暂无质量评估数据';
      tagsDiv.appendChild(badge);
    }
    
    // 质量评分详情
    const qualityDetails = card.querySelector('.quality-details');
    if (qa && qa.overall_score !== undefined) {
      qualityDetails.style.display = '';
      renderQualityDetails(qualityDetails, qa);
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
function renderOverflowList(keyword = '', startDate = '', endDate = '', qualityMin = 0) {
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

  // 质量分数筛选
  if (qualityMin > 0) {
    filtered = filtered.filter(item => {
      const score = item.quality_assessment && item.quality_assessment.overall_score;
      return score !== undefined && score >= qualityMin;
    });
  }

  // 排序
  filtered = sortPapers(filtered, sortBy, sortDir, keyword);
  
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

  // 质量评分
  const qa = item.quality_assessment;
  if (qa && qa.overall_score !== undefined) {
    const score = qa.overall_score;
    const level = score >= 80 ? 'excellent' : score >= 65 ? 'good' : score >= 50 ? 'fair' : 'poor';
    const stars = score >= 80 ? '★★★★★' : score >= 65 ? '★★★★' : score >= 50 ? '★★★' : '★★';
    const badge = document.createElement('div');
    badge.className = `quality-badge ${level}`;
    badge.style.marginTop = '4px';
    badge.style.display = 'inline-block';
    badge.innerHTML = `<span class="score">${score}</span><span>${stars}</span>`;
    content.appendChild(badge);

    // 质量详情展开
    const details = document.createElement('details');
    details.className = 'quality-details overflow-quality-details';
    details.style.marginTop = '8px';
    details.innerHTML = '<summary>📊 质量评分详情</summary>';
    const detailContent = document.createElement('div');
    detailContent.className = 'quality-detail-content';
    renderQualityDetailsInto(detailContent, qa);
    details.appendChild(detailContent);
    content.appendChild(details);
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

// ─────────────────────────────────────────────
// 质量评分详情渲染
// ─────────────────────────────────────────────
const _QDIM_LABELS = {
  novelty: '创新性',
  rigor: '技术严谨',
  data: '数据质量',
  impact: '实用价值',
  presentation: '表达质量'
};

function _dimColor(val) {
  if (val >= 80) return '#166534';
  if (val >= 65) return '#1e40af';
  if (val >= 50) return '#854d0e';
  return '#991b1b';
}

function renderQualityDetails(detailsEl, qa) {
  const content = detailsEl.querySelector('.quality-detail-content');
  if (!content) return;
  renderQualityDetailsInto(content, qa);
}

function renderQualityDetailsInto(container, qa) {
  container.innerHTML = '';
  if (!qa || qa.overall_score === undefined) return;

  // 综合评分
  const overallDiv = document.createElement('div');
  overallDiv.className = 'qa-overall';
  const confLabel = qa.confidence === 'high' ? '高' : qa.confidence === 'medium' ? '中' : '低';
  const confColor = qa.confidence === 'high' ? '#166534' : qa.confidence === 'medium' ? '#854d0e' : '#6b7280';
  overallDiv.innerHTML = `<strong>综合评分: ${qa.overall_score}/100</strong> <span style="color:${confColor};font-size:0.85em">（置信度: ${confLabel}）</span>`;
  container.appendChild(overallDiv);

  // 5维度
  const dimsDiv = document.createElement('div');
  dimsDiv.className = 'qa-dims';
  dimsDiv.style.marginTop = '10px';
  for (const [key, label] of Object.entries(_QDIM_LABELS)) {
    const val = qa[key];
    if (val === undefined || val === null) continue;
    const color = _dimColor(val);
    const pct = Math.max(0, Math.min(100, val));
    const row = document.createElement('div');
    row.className = 'qa-dim-row';
    row.innerHTML = `<span class="qa-dim-label">${label}</span>
      <div class="qa-dim-bar"><div class="qa-dim-fill" style="width:${pct}%;background:${color}"></div></div>
      <span class="qa-dim-value" style="color:${color}">${val}</span>`;
    dimsDiv.appendChild(row);
  }
  container.appendChild(dimsDiv);

  // 亮点
  if (qa.strengths && qa.strengths.length) {
    const sDiv = document.createElement('div');
    sDiv.className = 'qa-section';
    sDiv.innerHTML = '<div class="qa-section-title">✓ 亮点</div>';
    const ul = document.createElement('ul');
    qa.strengths.forEach(s => { const li = document.createElement('li'); li.textContent = s; ul.appendChild(li); });
    sDiv.appendChild(ul);
    container.appendChild(sDiv);
  }

  // 不足
  if (qa.limitations && qa.limitations.length) {
    const lDiv = document.createElement('div');
    lDiv.className = 'qa-section';
    lDiv.innerHTML = '<div class="qa-section-title">✗ 不足</div>';
    const ul = document.createElement('ul');
    qa.limitations.forEach(s => { const li = document.createElement('li'); li.textContent = s; ul.appendChild(li); });
    lDiv.appendChild(ul);
    container.appendChild(lDiv);
  }

  // 数据质量说明
  if (qa.data_quality_note) {
    const noteDiv = document.createElement('div');
    noteDiv.className = 'qa-section';
    noteDiv.innerHTML = `<div class="qa-section-title">📊 数据质量说明</div><p>${qa.data_quality_note}</p>`;
    container.appendChild(noteDiv);
  }

  // 评估理由
  if (qa.prediction_reason) {
    const reasonDiv = document.createElement('div');
    reasonDiv.className = 'qa-section';
    reasonDiv.innerHTML = `<div class="qa-section-title">💡 评估理由</div><p>${qa.prediction_reason}</p>`;
    container.appendChild(reasonDiv);
  }
}

// ─────────────────────────────────────────────
// 排序函数
// ─────────────────────────────────────────────
function calcRelevance(p, keyword) {
  if (!keyword) return 0;
  const kw = keyword.toLowerCase();
  let score = 0;
  if (p.title && p.title.toLowerCase().includes(kw))       score += 3;
  if (p.authors && p.authors.toLowerCase().includes(kw))  score += 2;
  if (p.affiliations && p.affiliations.toLowerCase().includes(kw)) score += 2;
  if (p.categories && p.categories.toLowerCase().includes(kw)) score += 1;
  if (p.abstract && p.abstract.toLowerCase().includes(kw)) score += 1;
  if (p.summary_cn && p.summary_cn.toLowerCase().includes(kw)) score += 1;
  return score;
}

function sortPapers(papers, sortBy, sortDir, keyword) {
  const sorted = [...papers];
  sorted.sort((a, b) => {
    let va, vb;

    if (sortBy === 'relevance') {
      if (keyword) {
        va = calcRelevance(a, keyword);
        vb = calcRelevance(b, keyword);
        if (va !== vb) return sortDir === 'desc' ? vb - va : va - vb;
        // 平分时 fallback 到发布时间
        va = a.published_date || '';
        vb = b.published_date || '';
      } else {
        // 无关键词，fallback 到发布时间
        va = a.published_date || '';
        vb = b.published_date || '';
      }
    } else if (sortBy === 'title') {
      va = (a.title || '').toLowerCase();
      vb = (b.title || '').toLowerCase();
      return sortDir === 'desc' ? vb.localeCompare(va) : va.localeCompare(vb);
    } else if (sortBy === 'quality_score') {
      // quality_assessment 缺失的论文排到最后
      const qa = p => p.quality_assessment && p.quality_assessment.overall_score !== undefined;
      va = qa(a) ? a.quality_assessment.overall_score : -1;
      vb = qa(b) ? b.quality_assessment.overall_score : -1;
      return sortDir === 'desc' ? vb - va : va - vb;
    } else {
      // published_date / crawled_date
      va = a[sortBy] || '';
      vb = b[sortBy] || '';
    }

    // 日期降序：b > a（更新日期在前）；升序：a > b
    if (sortDir === 'desc') return vb > va ? 1 : vb < va ? -1 : 0;
    return va > vb ? 1 : va < vb ? -1 : 0;
  });
  return sorted;
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
  const qualityMin = parseInt(els.qualityMin.value, 10);
  
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

    // 质量分数筛选
    if (qualityMin > 0) {
      const score = p.quality_assessment && p.quality_assessment.overall_score;
      if (score === undefined || score < qualityMin) return false;
    }

    // 关键词筛选
    if (keyword) {
      const searchText = `${p.title} ${p.authors} ${p.affiliations} ${p.abstract} ${p.summary_cn}`.toLowerCase();
      if (!searchText.includes(keyword)) return false;
    }

    return true;
  });

  // 排序（在筛选之后）
  filtered = sortPapers(filtered, sortBy, sortDir, keyword);

  renderCards(filtered);
  renderOverflowList(keyword, startDate, endDate, qualityMin);
}

// 重置筛选
function resetFilters() {
  els.keyword.value = '';
  els.favoriteOnly.checked = false;
  els.qualityMin.value = 0;
  els.qualityMinLabel.textContent = '0';
  els.qualityMin.style.setProperty('--pct', '0%');
  els.qualityMin.style.removeProperty('--slider-color');
  
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

// 排序控件事件
els.sortBy.addEventListener('change', () => {
  sortBy = els.sortBy.value;
  applyFilters();
});

els.sortDirBtn.addEventListener('click', () => {
  sortDir = sortDir === 'desc' ? 'asc' : 'desc';
  els.sortDirBtn.textContent = sortDir === 'desc' ? '↓' : '↑';
  els.sortDirBtn.title = sortDir === 'desc' ? '切换升序' : '切换降序';
  applyFilters();
});

// 质量滑块：实时更新标签 + 触发筛选
els.qualityMin.addEventListener('input', () => {
  const val = parseInt(els.qualityMin.value, 10);
  els.qualityMinLabel.textContent = val;
  // 实时更新滑块轨道填充色
  els.qualityMin.style.setProperty('--pct', val + '%');
  // 根据分数范围动态变色（与质量徽章分级一致）
  let color;
  if (val >= 80)      color = '#22c55e';      // excellent-绿色
  else if (val >= 65) color = '#3b82f6';     // good-蓝色
  else if (val >= 50) color = '#f59e0b';     // fair-黄色
  else                color = '#ef4444';     // poor-红色
  els.qualityMin.style.setProperty('--slider-color', color);
  applyFilters();
});

// 启动
init();
