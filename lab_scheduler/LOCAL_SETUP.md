# Guia de Configuração Local do Projeto Lab Scheduler

Este guia descreve como configurar e executar o projeto Flask "Lab Scheduler" localmente no seu ambiente de desenvolvimento, por exemplo, usando o VSCode.

## Pré-requisitos

*   Python 3.9 ou superior instalado.
*   `pip` (gerenciador de pacotes Python) instalado.
*   VSCode (ou outro editor de sua preferência) instalado.

## Passos para Configuração e Execução

1.  **Descompacte o Arquivo do Projeto:**
    *   Extraia o conteúdo do arquivo `lab_scheduler_project_no_venv.zip` (ou o nome do arquivo zip que você recebeu) para uma pasta de sua escolha no seu computador.

2.  **Abra o Projeto no VSCode:**
    *   Abra o VSCode.
    *   Vá em `File > Open Folder...` (Arquivo > Abrir Pasta...) e selecione a pasta onde você descompactou o projeto.

3.  **Crie um Ambiente Virtual (venv):**
    *   Abra um novo terminal integrado no VSCode (`Terminal > New Terminal` ou `Ctrl+\`).
    *   Certifique-se de que você está na pasta raiz do projeto (ex: `lab_scheduler`).
    *   Execute o seguinte comando para criar um ambiente virtual chamado `venv`:
        ```bash
        python -m venv venv
        ```
        *Se você tiver múltiplas versões do Python, pode precisar usar `python3 -m venv venv`.*

4.  **Ative o Ambiente Virtual:**
    *   **No Windows (PowerShell/CMD):**
        ```bash
        .\venv\Scripts\activate
        ```
    *   **No macOS ou Linux (bash/zsh):**
        ```bash
        source venv/bin/activate
        ```
    *   Após a ativação, você deverá ver `(venv)` no início do prompt do seu terminal, indicando que o ambiente virtual está ativo.

5.  **Instale as Dependências:**
    *   Com o ambiente virtual ainda ativo, instale todas as bibliotecas Python necessárias listadas no arquivo `requirements.txt`. Execute:
        ```bash
        pip install -r requirements.txt
        ```

6.  **Execute a Aplicação Flask:**
    *   O arquivo principal da aplicação é `src/main.py`.
    *   Para iniciar o servidor de desenvolvimento Flask, execute:
        ```bash
        python src/main.py
        ```
        *Novamente, pode ser `python3 src/main.py` dependendo da sua configuração.*
    *   O terminal mostrará mensagens indicando que o servidor está rodando, geralmente em um endereço como `http://127.0.0.1:5000/`.

7.  **Acesse a Aplicação no Navegador:**
    *   Abra seu navegador de internet (Chrome, Firefox, Edge, etc.).
    *   Digite o endereço fornecido no terminal (geralmente `http://127.0.0.1:5000/`) na barra de endereços e pressione Enter.
    *   Você deverá ver a interface do aplicativo de agendamento de laboratório.

## Banco de Dados

*   O projeto utiliza um banco de dados SQLite.
*   O arquivo do banco de dados é `lab_scheduler.db` e está localizado na pasta raiz do projeto.
*   Quando você executa a aplicação pela primeira vez (`python src/main.py`), o Flask-SQLAlchemy (a biblioteca que gerencia o banco de dados) criará automaticamente este arquivo e as tabelas necessárias se eles não existirem.
*   Todos os agendamentos feitos através da interface serão salvos neste arquivo.

## Observações Adicionais

*   **Desativar Ambiente Virtual:** Quando terminar de trabalhar no projeto, você pode desativar o ambiente virtual digitando `deactivate` no terminal.
*   **Variáveis de Ambiente para E-mail:** A funcionalidade de envio de e-mail (descrita no guia do usuário principal) requer configuração de variáveis de ambiente para o servidor SMTP. Para desenvolvimento local, se você não configurar essas variáveis, o envio de e-mail pode falhar ou ser suprimido, dependendo da configuração em `src/main.py` (a linha `app.config['MAIL_SUPPRESS_SEND'] = True` suprime os e-mails).

Se encontrar qualquer problema durante a configuração, verifique as mensagens de erro no terminal, certifique-se de que o ambiente virtual está ativo e que todas as dependências foram instaladas corretamente.
