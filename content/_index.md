---
# Leave the homepage title empty to use the site title
title: ''
summary: ''
date: 2026-09-14
type: landing

sections:
  # ---------- 个人简介（首屏） ----------
  - block: resume-biography-3
    content:
      username: me
      text: ''
      button:
        text: Google Scholar
        url: https://scholar.google.com/citations?user=EwomMksAAAAJ
      headings:
        about: ''
        education: ''
        interests: ''
    design:
      background:
        gradient_mesh:
          enable: true
      name:
        size: md
      avatar:
        size: medium
        shape: circle

  # ---------- 最新动态 ----------
  - block: collection
    id: news
    content:
      title: 📰 Recent News
      subtitle: ''
      count: 5
      filters:
        folders:
          - news
      sort_by: date
      sort_ascending: false
    design:
      view: date-title-summary
      columns: 1

  # ---------- 研究方向 ----------
  - block: markdown
    content:
      title: '🔬 Research'
      subtitle: ''
      text: |-
        I build **machine learning algorithms for graph-structured data and database systems**.

        My work spans two directions: (1) **graph neural network architectures** that model complex,
        heterogeneous or incomplete graphs — fraud detection on e-commerce platforms, graph similarity
        computation, supergraph containment search and malware detection; and (2) **learning-based
        methods for data management** — using graph learning and representation techniques to speed up
        the algorithms behind databases and data-mining systems.

        Recent work has appeared in **KDD 2023** and **IEEE TKDE (2024, 2025, 2026)**.
    design:
      columns: '1'

  # ---------- 代表性论文 ----------
  - block: collection
    id: publications
    content:
      title: 📄 Selected Publications
      subtitle: First-author papers in CCF-A venues. **[→ Full publication list](/publications/)** (auto-synced from OpenAlex/ORCID, with CCF / 中科院分区 / JCR badges)
      filters:
        folders:
          - publications
        featured_only: true
    design:
      view: citation
      columns: 1

  # ---------- 学术服务 ----------
  - block: markdown
    id: services
    content:
      title: '🧑‍🏫 Academic Services'
      subtitle: ''
      text: |-
        **Peer Reviewing**

        - Reviewer, *IEEE Transactions on Knowledge and Data Engineering* (TKDE), 2025 —

        **Teaching**

        - Guest Lecturer, *43023 Emerging Topics in Artificial Intelligence*, University of Technology Sydney, Spring 2025

        **Community**

        - Student Volunteer / session support, research seminars of the Data Science and Machine Learning group, UTS, 2024 —
    design:
      columns: '1'

  # ---------- 荣誉奖励 ----------
  - block: resume-awards
    id: awards
    content:
      title: '🏆 Awards & Honors'
      username: me
---
