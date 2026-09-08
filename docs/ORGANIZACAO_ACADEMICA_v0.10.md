# Organização acadêmica — v0.10-alpha.1

A estrutura canônica do curso agora é lida diretamente dos índices acadêmicos existentes no Projeto E v2.39.

## Hierarquia

`Disciplina → campo acadêmico → módulo/subcampo → tópico → materiais`

Os campos e a ordem são herdados dos índices do curso anterior. Em Matemática, por exemplo, a ordem canônica começa por **Números e Álgebra**, **Análise Elementar**, **Geometria** e **Estatística**. Em Física, começa por **Fundamentos de Física e Medição**, **Mecânica Clássica**, **Termologia e Termodinâmica**, **Oscilações, Ondas e Acústica**, **Óptica**, **Eletromagnetismo Clássico** e **Física Moderna, Nuclear e Cosmologia**.

A v0.9 já havia importado os materiais, mas a ordem de alguns módulos vinha da ordem física de leitura dos arquivos e podia aparecer embaralhada. A v0.10 passa a usar a ordem declarada nos próprios índices do curso.

## BNCC

A BNCC não participa da árvore acima. `busca_bncc/fila_de_busca_v1.json` é apenas uma ferramenta interna de descoberta de vídeos. Uma indicação de material legado nesse arquivo não é uma classificação curricular: apenas evita pesquisar novamente algo que talvez já esteja no acervo.
