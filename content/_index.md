---
# Leave the homepage title empty to use the site title
title: ''
summary: ''
date: 2026-09-14
type: landing

sections:
  - block: resume-biography-3
    content:
      username: me
      text: ''
      # Call-to-action button under the biography
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

  - block: markdown
    content:
      title: '🔬 Research'
      subtitle: ''
      text: |-
        I build **machine learning algorithms for graph-structured data and database systems**.

        My work spans two directions: (1) **graph neural network architectures** that model
        complex, heterogeneous or incomplete graphs — for fraud detection on e-commerce platforms,
        graph similarity computation, supergraph containment search and malware detection;
        and (2) **learning-based methods for data management** — using graph learning and
        representation techniques to speed up and improve the algorithms behind databases
        and data-mining systems.

        Recent work has appeared in **KDD 2023** and **IEEE TKDE (2024, 2025, 2026)**.
        I am also interested in knowledge graphs and their applications to
        data-intensive domains. Feel free to reach out for collaboration.
    design:
      columns: '1'

  - block: collection
    id: papers
    content:
      title: Featured Publications
      subtitle: ''
      filters:
        folders:
          - publications
        featured_only: true
    design:
      view: article-grid
      columns: 2

  - block: collection
    id: publications
    content:
      title: Publications
      subtitle: 'Full list — auto-synced from OpenAlex/ORCID, with CCF & SCI classification badges'
      count: 0
      filters:
        folders:
          - publications
      sort_by: date
      sort_ascending: false
    design:
      view: citation
      columns: 1
---
