# Relatório do Projeto E — v0.208-alpha.1

## Objetivo da rodada

Reorganizar a interface para reduzir a quantidade de informação simultânea e facilitar a navegação do aluno, sem alterar o corpus acadêmico ou o conjunto de URLs.

## Mudanças implementadas

- navegação hierárquica compacta por **disciplina → área → módulo**;
- conteúdo principal em modelo **mestre-detalhe**, com a lista de tópicos à esquerda e apenas um tópico aberto por vez;
- remoção dos chips repetidos de fonte em cada linha de tópico; a fonte aparece somente quando a videoaula do tópico é exibida;
- busca global preservada, agora levando diretamente ao módulo e tópico correto;
- filtros de módulo: **Todos / Com aula / Lacunas**;
- botões **Anterior / Próximo** para estudo sequencial;
- resumo estatístico da disciplina movido para disclosure secundário (“Sobre esta disciplina”);
- menu lateral responsivo em telas menores;
- melhorias de acessibilidade: skip link, foco visível, ARIA, navegação por teclado e respeito a `prefers-reduced-motion`;
- interface continua autocontida e offline, sem bibliotecas ou fontes externas.

## Princípios usados

A revisão seguiu princípios de divulgação progressiva, hierarquia de navegação rasa, estado atual visível e requisitos de navegabilidade/acessibilidade. As referências de pesquisa utilizadas foram Nielsen Norman Group, Carbon Design System, U.S. Web Design System e WCAG 2.2.

## Conteúdo e políticas

Nenhuma associação tópico→vídeo foi adicionada ou removida. O conjunto de 739 URLs permanece igual ao da v0.207-alpha.1. Os arquivos de auditoria de dados permanecem v0.207 porque não houve rodada de cobertura nem rechecagem externa de links.
