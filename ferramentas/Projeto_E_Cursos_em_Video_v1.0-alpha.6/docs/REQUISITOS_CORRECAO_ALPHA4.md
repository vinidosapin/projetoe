# Requisitos verificáveis da alpha.4

## Escopo

A `v1.0-alpha.4` deve operar com materiais educacionais reais e heterogêneos
sem corromper o workspace, explodir o mapa heurístico ou confundir resultado de
busca com aula adequada. “Funcional” significa concluir o contrato ou registrar
uma lacuna explícita e retomável; não significa alegar que existe vídeo adequado
para toda unidade da internet.

## Requisitos obrigatórios

1. A versão é uma pasta irmã isolada, derivada diretamente da `alpha.3`, cuja
   árvore permanece imutável e conferível pela baseline.
2. `ingest` e `create` são transações: limite, extrator ou planejamento que
   falhe não pode deixar manifesto, mapa, prompt ou diretório parcial publicado.
3. `--input ""` e `--source ""` são erros. String vazia nunca pode significar o
   diretório corrente nem ingerir silenciosamente a própria release.
4. Os limites padrão comportam materiais acadêmicos reais: 64 MiB por arquivo e
   URL, 200 MiB no conjunto/ZIP e 32 milhões de caracteres extraídos.
5. Um mapa V0 contém no máximo 32 unidades por fonte e 128 no conjunto,
   representa ao menos uma unidade por fonte e preserva a faixa completa de
   páginas/seções. O texto integral continua no diretório `ingest/text/`.
6. PDF sem camada textual informa a lacuna e oferece OCR apenas por opt-in com
   `--ocr-scanned-pdf`. O OCR limita páginas, trabalha página a página e escolhe
   os idiomas do Tesseract realmente instalados. Imagens seguem a mesma regra de
   idioma disponível.
7. A extração declarada para texto, código, HTML/XML, notebook, ZIP, PDF,
   imagem, DOCX, PPTX, XLSX, ODT, ODS, ODP e EPUB deve ter teste. Formatos que
   existem no Dropbox também precisam de execução real externa à release.
8. O plano de busca deve separar objeto exato, descoberta do ecossistema e
   equivalente rigoroso. Consultas genéricas não podem carregar listas de
   autores/livros; consultas equivalentes devem usar o objeto estrutural curto.
   Tradução ausente permanece `LOCALIZATION_REQUIRED`.
9. Busca deve ser retomável, aberta a qualquer idioma e sem API key. Metadados
   podem ordenar a inspeção, mas nunca aprovar vídeo, conteúdo ou dublagem.
10. Toda rota liberada continua exigindo inspeção interna passo a passo,
    timestamps, evidência audiovisual e uma faixa PT/EN realmente ouvida. Curso
    sem essa evidência permanece `PARCIAL` e soma zero tempo útil.
11. Os pilotos, fontes, OCR, frames, áudio e transcrições ficam fora da versão.
    O ZIP contém somente código, contratos, exemplos, testes e documentação.
12. O fechamento exige suíte offline completa, demo, validação de workspaces
    reais, validação da baseline, instalação limpa da pasta e do ZIP, `pip
    check`, auditoria de segredos e ZIP reproduzível com uma única raiz.

## Casos reais mínimos

- livro TXT acima de 4 MB;
- PDF textual acima do antigo limite de 20 MiB;
- PDF digitalizado com OCR real ao menos em uma página;
- corpus conjunto com livros, slides PDF/PPTX, ZIP de exercícios, códigos R e
  Python, Markdown, CSV, XLSX, JSON, artigo PDF e ODT;
- exercício em imagem com OCR, exercício em LaTeX e HTML;
- mapa V1, busca PT/EN/ES, coleta e auditoria de candidatos sem aprovação por
  título, descrição ou resultado da consulta.

## Critério de aceite

A release somente fecha quando todos os requisitos acima possuem regressão ou
evidência real registrada, `validate-release --require-origin` passa na pasta e
no ZIP, e o manifesto mantém `promotion_ready=false`. Busca ou vídeo ausente é
uma lacuna válida; estado parcial ou corrupção silenciosa não é.
