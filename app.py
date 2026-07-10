import streamlit as st
import pandas as pd
import psycopg2
import json
import base64
import datetime

st.set_page_config(layout="wide", page_title="Sistema de Produção Militar")

# =============================================================================
# 1. FUNÇÕES DO BANCO DE DADOS (SUPABASE)
# =============================================================================
# forçando atualização de dependências
def conectar_db():
    return psycopg2.connect(st.secrets["DATABASE_URL"])

def criar_tabelas():
    conn = conectar_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS insumos (
            nome TEXT PRIMARY KEY,
            unidade TEXT,
            estoque DOUBLE PRECISION,
            custo_unitario DOUBLE PRECISION
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS produtos (
            nome TEXT PRIMARY KEY,
            grade TEXT,
            receita TEXT,
            foto BYTEA
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ops (
            id_op TEXT PRIMARY KEY,
            produto TEXT,
            tamanho TEXT,
            quantidade INTEGER,
            status TEXT,
            custo_total DOUBLE PRECISION
        )
    ''')
    
    cursor.execute("ALTER TABLE ops ADD COLUMN IF NOT EXISTS custo_mo DOUBLE PRECISION DEFAULT 0.0")
    cursor.execute("ALTER TABLE ops ADD COLUMN IF NOT EXISTS tempo_gasto TEXT DEFAULT ''")
    
    conn.commit()
    conn.close()

criar_tabelas()

# =============================================================================
# MENU LATERAL
# =============================================================================
st.sidebar.image("https://cdn-icons-png.flaticon.com/512/2097/2097276.png", width=100)
st.sidebar.title("Navegação")
menu = st.sidebar.radio(
    "Escolha o módulo:",
    [
        "📊 Dashboard & DRE",
        "📋 OPs Ativas", 
        "⏱️ Apontamento de Horas",
        "📚 Histórico de OPs",
        "📦 Estoque (Entradas/Saídas)",
        "🛠️ Fichas Técnicas", 
        "⚙️ Cadastro de Insumos"
    ]
)

st.title("A CASERNA - Gestão e Controle de Produção")

# =============================================================================
# MÓDULO 1: DASHBOARD FINANCEIRO E OPERACIONAL
# =============================================================================
if menu == "📊 Dashboard & DRE":
    st.subheader("Indicadores de Desempenho da Fábrica")
    
    conn = conectar_db()
    df_ops_dash = pd.read_sql("SELECT * FROM ops", conn)
    conn.close()
    
    if df_ops_dash.empty:
        st.info("💡 O Dashboard aparecerá assim que você lançar e concluir as primeiras Ordens de Produção.")
    else:
        total_ops_lancadas = len(df_ops_dash)
        ops_concluidas = len(df_ops_dash[df_ops_dash['status'] == 'Concluída'])
        total_pecas_produzidas = df_ops_dash[df_ops_dash['status'] == 'Concluída']['quantidade'].sum()
        cmv_total_acumulado = df_ops_dash[df_ops_dash['status'] == 'Concluída']['custo_total'].sum()
        
        card1, card2, card3, card4 = st.columns(4)
        with card1:
            st.metric("Total de OPs Criadas", total_ops_lancadas)
        with card2:
            st.metric("OPs Concluídas ✅", ops_concluidas)
        with card3:
            st.metric("Total de Peças Produzidas", f"{total_pecas_produzidas} un")
        with card4:
            st.metric("Custo Geral Acumulado", f"R$ {cmv_total_acumulado:.2f}", delta_color="inverse")
            
        st.divider()
        
        col_grafico, col_dre = st.columns([1, 1])
        
        with col_grafico:
            st.subheader("Custos de Produção por Produto")
            df_custo_prod = df_ops_dash[df_ops_dash['status'] == 'Concluída'].groupby('produto').agg(
                Quantidade_Total=('quantidade', 'sum'),
                Custo_Total_CMV=('custo_total', 'sum')
            ).reset_index()
            
            if not df_custo_prod.empty:
                df_custo_prod['Custo Médio p/ Peça'] = df_custo_prod['Custo_Total_CMV'] / df_custo_prod['Quantidade_Total']
                maior_custo = float(df_custo_prod['Custo_Total_CMV'].max())
                st.dataframe(
                    df_custo_prod,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "produto": st.column_config.TextColumn("Produto"),
                        "Quantidade_Total": st.column_config.NumberColumn("Qtd Produzida"),
                        "Custo_Total_CMV": st.column_config.ProgressColumn("Custo Total (CMV)", format="R$ %.2f", min_value=0, max_value=maior_custo),
                        "Custo Médio p/ Peça": st.column_config.NumberColumn("Custo Médio Unit.", format="R$ %.2f")
                    }
                )
            else:
                st.caption("Aguardando conclusão de OPs para gerar a análise de custos.")
                
        with col_dre:
            st.subheader("Demonstração do Resultado Simplificada (DRE)")
            receita_vendas = st.number_input("Receita Bruta de Vendas (R$):", min_value=0.0, step=1000.0, format="%.2f")
            lucro_bruto = receita_vendas - cmv_total_acumulado
            margem_bruta = (lucro_bruto / receita_vendas * 100) if receita_vendas > 0 else 0.0
            
            st.write("---")
            with st.container(border=True):
                st.markdown(f"**(+) RECEITA BRUTA DE VENDAS:** R$ {receita_vendas:.2f}")
                st.markdown(f"**(-) CUSTO DAS MERCADORIAS (MATERIAL + MÃO DE OBRA):** R$ {cmv_total_acumulado:.2f}")
                st.write("---")
                if lucro_bruto >= 0:
                    st.markdown(f"### 💰 RESULTADO BRUTO DO PERÍODO: R$ {lucro_bruto:.2f}")
                    st.success(f"**Margem Bruta:** {margem_bruta:.2f}%")
                else:
                    st.markdown(f"### 🔻 RESULTADO BRUTO DO PERÍODO: R$ {lucro_bruto:.2f}")
                    st.error(f"**Atenção:** Operação registrando prejuízo bruto de {margem_bruta:.2f}%")

# =============================================================================
# MÓDULO 2: OPs ATIVAS
# =============================================================================
elif menu == "📋 OPs Ativas":
    st.subheader("Gestão de OPs Ativas (Fila de Produção)")
    
    conn = conectar_db()
    cursor = conn.cursor()
    cursor.execute("SELECT nome, grade, receita, foto FROM produtos")
    produtos_db = cursor.fetchall()
    cursor.execute("SELECT nome, custo_unitario FROM insumos")
    custos_atuais = {row[0]: row[1] for row in cursor.fetchall()}
    df_ops = pd.read_sql("SELECT * FROM ops WHERE status = 'Pendente'", conn)
    conn.close()
    
    fichas_tecnicas = {p[0]: {"grade": json.loads(p[1]), "receita": json.loads(p[2]), "foto": bytes(p[3]) if p[3] else None} for p in produtos_db}
    produtos_disp = list(fichas_tecnicas.keys())
    
    if produtos_disp:
        with st.expander("➕ Lançar Nova Ordem de Produção", expanded=True):
            col1, col2, col3 = st.columns(3)
            with col1:
                prod_sel = st.selectbox("Produto", produtos_disp)
            with col2:
                tam_sel = st.selectbox("Tamanho", fichas_tecnicas[prod_sel]['grade'])
            with col3:
                qtd_dig = st.number_input("Quantidade a Produzir", min_value=1, step=1)

            if st.button("Criar OP"):
                conn = conectar_db()
                cursor = conn.cursor()
                cursor.execute("SELECT id_op FROM ops")
                novo_id = f"OP-{(len(cursor.fetchall()) + 1):03d}"
                cursor.execute("INSERT INTO ops (id_op, produto, tamanho, quantidade, status, custo_total) VALUES (%s, %s, %s, %s, 'Pendente', 0.0)", (novo_id, prod_sel, tam_sel, qtd_dig))
                conn.commit()
                conn.close()
                st.success(f"{novo_id} gerada com sucesso!")
                st.rerun()

    st.write("---")
    
    if not df_ops.empty:
        for index, row in df_ops.iterrows():
            id_op = row['id_op']
            prod = row['produto']
            tam = row['tamanho']
            qtd = int(row['quantidade'])
            status = row['status']
            
            with st.container(border=True):
                c_foto, c_info, c_mat, c_acao = st.columns([1.2, 2, 3, 2])
                
                ficha = fichas_tecnicas.get(prod, {})
                receita = ficha.get("receita", {})
                foto_blob = ficha.get("foto")
                
                with c_foto:
                    if foto_blob:
                        st.image(foto_blob, use_container_width=True)
                    else:
                        st.caption("📷 Sem foto")
                
                with c_info:
                    st.markdown(f"### {id_op}")
                    st.markdown(f"**{prod}** | Tam: {tam} | Qtd: {qtd}")
                    st.warning(f"Status: {status} ⏳")
                    
                with c_mat:
                    st.write("**Romaneio de Produção:**")
                    for insumo, det in receita.items():
                        st.write(f"• {det['quantidade'] * qtd:.2f} {det['unidade']} de {insumo}")
                            
                with c_acao:
                    custo_estimado = sum((det['quantidade'] * qtd) * custos_atuais.get(insumo, 0.0) for insumo, det in receita.items())
                    st.markdown(f"**CMV Estimado (Só Material): R$ {custo_estimado:.2f}**")
                    
                    st.write("---")
                    st.caption("Para concluir apontando a mão de obra e os dias trabalhados, vá na aba **Apontamento de Horas**.")
                    
                    if st.button(f"✅ Conclusão Rápida (Sem Mão de Obra)", key=f"concluir_{id_op}"):
                        conn = conectar_db()
                        cursor = conn.cursor()
                        custo_real = 0.0
                        
                        for insumo, det in receita.items():
                            consumo_total = det['quantidade'] * qtd
                            c_unit = custos_atuais.get(insumo, 0.0)
                            custo_real += (consumo_total * c_unit)
                            cursor.execute("UPDATE insumos SET estoque = estoque - %s WHERE nome = %s", (consumo_total, insumo))
                            
                        cursor.execute("UPDATE ops SET status = 'Concluída', custo_total = %s WHERE id_op = %s", (custo_real, id_op))
                        conn.commit()
                        conn.close()
                        st.rerun()
                    
                    if st.button(f"🗑️ Cancelar OP", key=f"cancel_{id_op}"):
                        conn = conectar_db()
                        cursor = conn.cursor()
                        cursor.execute("DELETE FROM ops WHERE id_op = %s", (id_op,))
                        conn.commit()
                        conn.close()
                        st.rerun()
                    
                    data_atual = datetime.datetime.now().strftime("%d/%m/%Y")
                    
                    html_linhas = ""
                    for insumo, det in receita.items():
                        html_linhas += f"<tr><td>{insumo}</td><td style='text-align: center;'>{det['quantidade']:.2f}</td><td style='text-align: center;'><strong>{det['quantidade'] * qtd:.2f}</strong></td><td>{det['unidade']}</td><td style='text-align: center; color: #ccc;'>[  ]</td></tr>"
                    
                    img_html = f'<img src="data:image/jpeg;base64,{base64.b64encode(foto_blob).decode("utf-8")}" style="max-width: 100%; max-height: 120px; object-fit: contain; border-radius: 4px;">' if foto_blob else '<span style="color: #999; font-size: 11px;">FOTO NÃO CADASTRADA</span>'
                    
                    html_romaneio = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Romaneio_{id_op}</title><style>body {{ font-family: Arial, sans-serif; margin: 35px; color: #222; }} .header {{ text-align: center; border-bottom: 3px double #111; padding-bottom: 10px; margin-bottom: 25px; }} .header h1 {{ margin: 0; font-size: 24px; font-weight: bold; }} .info-table {{ width: 100%; margin-bottom: 25px; border-collapse: collapse; }} .info-table td {{ padding: 9px; border: 1px solid #999; font-size: 13px; }} .info-table td.label {{ font-weight: bold; background-color: #f7f7f7; width: 20%; }} .section-title {{ font-size: 14px; font-weight: bold; margin-top: 25px; background-color: #111; color: #fff; padding: 6px 10px; }} .materials-table {{ width: 100%; border-collapse: collapse; margin-top: 5px; }} .materials-table th, .materials-table td {{ border: 1px solid #444; padding: 9px; font-size: 13px; }} .materials-table th {{ background-color: #dddddd; font-weight: bold; }} .signatures {{ margin-top: 70px; width: 100%; border-collapse: collapse; }} .signatures td {{ width: 50%; text-align: center; vertical-align: bottom; height: 50px; font-size: 12px; }} .line {{ border-top: 1px solid #333; width: 75%; margin: 0 auto 6px auto; }}</style></head><body><div class="header"><h1>A CASERNA DESDE 1977</h1><h2>ROMANEIO OPERACIONAL DE PRODUÇÃO</h2></div><table class="info-table"><tr><td rowspan="5" style="width: 140px; text-align: center; vertical-align: middle; padding: 5px; background-color: #fcfcfc;">{img_html}</td><td class="label">Código da OP:</td><td><strong>{id_op}</strong></td><td class="label">Data de Emissão:</td><td><strong>{data_atual}</strong></td></tr><tr><td class="label">Produto Final:</td><td>{prod}</td><td class="label">Grade / Tamanho:</td><td>{tam}</td></tr><tr><td class="label">Qtd Programada:</td><td><strong>{qtd} un</strong></td><td class="label">Custo Material Estimado:</td><td>R$ {custo_estimado:.2f}</td></tr><tr><td class="label">Início da OP:</td><td>___/___/___ às ___:___</td><td class="label">Término da OP:</td><td>___/___/___ às ___:___</td></tr><tr><td class="label">Valor Combinado/Hora:</td><td>R$ _____</td><td class="label">Total Mão de Obra:</td><td><strong>R$ _____</strong></td></tr></table><div class="section-title">EXPLOSÃO DE MATERIAIS (SEPARAÇÃO E CORTE)</div><table class="materials-table"><thead><tr><th>Descrição da Matéria-Prima / Insumo</th><th style="text-align: center;">Consumo Unit.</th><th style="text-align: center;">Qtd Total Requerida</th><th>Unidade</th><th style="text-align: center;">Conferido</th></tr></thead><tbody>{html_linhas}</tbody></table><table class="signatures"><tr><td><div class="line"></div>Responsável pela Separação</td><td><div class="line"></div>João (Chão de Fábrica)</td></tr></table><script>window.onload = function() {{ window.print(); }}</script></body></html>"""
                    st.write("")
                    st.download_button(label="🖨️ Imprimir Romaneio p/ João", data=html_romaneio, file_name=f"romaneio_{id_op}.html", mime="text/html", key=f"print_{id_op}")
    else:
        st.info("Nenhuma OP pendente no momento. O chão de fábrica está livre!")

# =============================================================================
# MÓDULO 3: APONTAMENTO DE HORAS E FECHAMENTO
# =============================================================================
elif menu == "⏱️ Apontamento de Horas":
    st.subheader("⏱️ Fechamento e Custeio de Mão de Obra")
    st.write("Insira as datas e horas exatas anotadas no Romaneio. O sistema calcula automaticamente o tempo considerando que o expediente é das 08:00 às 17:00.")
    
    conn = conectar_db()
    df_ops_pend = pd.read_sql("SELECT * FROM ops WHERE status = 'Pendente'", conn)
    cursor = conn.cursor()
    cursor.execute("SELECT nome, custo_unitario FROM insumos")
    custos_atuais = {row[0]: row[1] for row in cursor.fetchall()}
    cursor.execute("SELECT nome, receita FROM produtos")
    receitas = {row[0]: json.loads(row[1]) for row in cursor.fetchall()}
    conn.close()

    if df_ops_pend.empty:
        st.info("🎉 Nenhuma OP pendente no momento! Todas já foram fechadas.")
    else:
        op_sel = st.selectbox("Selecione a OP para Fechamento:", df_ops_pend['id_op'].tolist())
        row_op = df_ops_pend[df_ops_pend['id_op'] == op_sel].iloc[0]
        prod = row_op['produto']
        qtd = int(row_op['quantidade'])
        receita = receitas.get(prod, {})

        custo_material_real = sum((det['quantidade'] * qtd) * custos_atuais.get(insumo, 0.0) for insumo, det in receita.items())

        with st.container(border=True):
            st.markdown(f"**OP Selecionada:** {op_sel} | **Produto:** {prod} | **Quantidade:** {qtd} un")
            st.write("---")

            col_d1, col_h1, col_d2, col_h2 = st.columns(4)
            with col_d1:
                d_inicio = st.date_input("Data de Início", value=datetime.date.today())
            with col_h1:
                h_inicio = st.time_input("Horário de Início", value=datetime.time(8, 0))
            with col_d2:
                d_fim = st.date_input("Data de Término", value=datetime.date.today())
            with col_h2:
                h_fim = st.time_input("Horário de Término", value=datetime.time(17, 0))

            h1_dec = h_inicio.hour + h_inicio.minute / 60.0
            h2_dec = h_fim.hour + h_fim.minute / 60.0
            
            h1_dec = max(8.0, min(17.0, h1_dec))
            h2_dec = max(8.0, min(17.0, h2_dec))

            dias_diff = (d_fim - d_inicio).days

            if dias_diff < 0:
                st.error("A Data de Término não pode ser anterior à Data de Início.")
                horas_calc = 0.0
            elif dias_diff == 0:
                horas_calc = max(0.0, h2_dec - h1_dec)
            else:
                horas_primeiro_dia = 17.0 - h1_dec
                horas_ultimo_dia = h2_dec - 8.0
                dias_intermediarios = dias_diff - 1
                horas_calc = horas_primeiro_dia + (dias_intermediarios * 9.0) + horas_ultimo_dia

            st.write("---")
            
            valor_hora = 20.06  
            st.info(f"💡 Valor da Hora Trabalhada Automatizado: **R$ {valor_hora:.2f}** (Inclui Provisão de Férias, 13º salário e encargos)")
            
            horas_finais = st.number_input("Tempo Calculado (Horas Decimais) - Ajuste se necessário:", min_value=0.0, value=float(max(0.0, horas_calc)), step=0.5)
            
            custo_mo_real = horas_finais * valor_hora
            custo_geral_total = custo_material_real + custo_mo_real

            st.write("---")
            c_res1, c_res2, c_res3, c_res4 = st.columns(4)
            c_res1.metric("Tempo Final a Pagar", f"{horas_finais:.2f} hrs")
            c_res2.metric("Custo do Material", f"R$ {custo_material_real:.2f}")
            c_res3.metric("Custo Mão de Obra", f"R$ {custo_mo_real:.2f}")
            c_res4.metric("CUSTO GERAL (Total)", f"R$ {custo_geral_total:.2f}")

            st.write("")
            if st.button("✅ Confirmar Fechamento e Baixar Estoque", type="primary"):
                conn = conectar_db()
                cursor = conn.cursor()
                
                for insumo, det in receita.items():
                    consumo_total = det['quantidade'] * qtd
                    cursor.execute("UPDATE insumos SET estoque = estoque - %s WHERE nome = %s", (consumo_total, insumo))

                cursor.execute("""
                    UPDATE ops 
                    SET status = 'Concluída', custo_total = %s, custo_mo = %s, tempo_gasto = %s
                    WHERE id_op = %s
                """, (custo_geral_total, custo_mo_real, f"{horas_finais:.2f}h", op_sel))

                conn.commit()
                conn.close()
                st.success(f"Excelente! {op_sel} foi fechada com sucesso.")
                st.rerun()

# =============================================================================
# MÓDULO 4: HISTÓRICO DE OPs
# =============================================================================
elif menu == "📚 Histórico de OPs":
    st.subheader("📚 Histórico de OPs Concluídas")
    
    conn = conectar_db()
    df_ops_hist = pd.read_sql("SELECT * FROM ops WHERE status = 'Concluída' ORDER BY id_op DESC", conn)
    conn.close()
    
    if not df_ops_hist.empty:
        for index, row in df_ops_hist.iterrows():
            id_op = row['id_op']
            prod = row['produto']
            tam = row['tamanho']
            qtd = int(row['quantidade'])
            status = row['status']
            
            custo_final = float(row['custo_total'] if pd.notna(row['custo_total']) else 0.0)
            custo_mo = float(row['custo_mo']) if 'custo_mo' in row and pd.notna(row['custo_mo']) else 0.0
            tempo_gasto = row['tempo_gasto'] if 'tempo_gasto' in row and pd.notna(row['tempo_gasto']) else ""
            custo_mat = custo_final - custo_mo
            
            with st.container(border=True):
                c_foto, c_info, c_mat, c_custo = st.columns([1.2, 2, 3, 2])
                conn = conectar_db()
                cursor = conn.cursor()
                cursor.execute("SELECT receita, foto FROM produtos WHERE nome = %s", (prod,))
                p_data = cursor.fetchone()
                conn.close()
                
                receita = json.loads(p_data[0]) if p_data else {}
                foto_blob = bytes(p_data[1]) if p_data and p_data[1] else None
                
                with c_foto:
                    if foto_blob: st.image(foto_blob, use_container_width=True)
                
                with c_info:
                    st.markdown(f"### {id_op}")
                    st.markdown(f"**{prod}** | Tam: {tam} | Qtd: {qtd}")
                    st.success(f"Status: {status} ✅")
                    
                with c_mat:
                    st.write("**Romaneio Utilizado:**")
                    for insumo, det in receita.items():
                        st.write(f"• {det['quantidade'] * qtd:.2f} {det['unidade']} de {insumo}")
                            
                with c_custo:
                    st.markdown(f"💰 **Custo Geral: R$ {custo_final:.2f}**")
                    st.caption(f"Custo Unitário da peça: R$ {custo_final/qtd:.2f}")
                    
                    if custo_mo > 0:
                        st.write(f"- Material: R$ {custo_mat:.2f}")
                        st.write(f"- Mão de Obra: R$ {custo_mo:.2f} ({tempo_gasto})")
                    else:
                        st.write("- Sem apontamento de horas.")
                    
                    html_linhas = ""
                    for insumo, det in receita.items():
                        html_linhas += f"<tr><td>{insumo}</td><td style='text-align: center;'>{det['quantidade']:.2f}</td><td style='text-align: center;'><strong>{det['quantidade'] * qtd:.2f}</strong></td><td>{det['unidade']}</td><td style='text-align: center; color: #ccc;'>[  ]</td></tr>"
                    
                    img_html = f'<img src="data:image/jpeg;base64,{base64.b64encode(foto_blob).decode("utf-8")}" style="max-width: 100%; max-height: 120px; object-fit: contain; border-radius: 4px;">' if foto_blob else '<span style="color: #999; font-size: 11px;">FOTO NÃO CADASTRADA</span>'
                    html_romaneio_hist = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Romaneio_{id_op}</title><style>body {{ font-family: Arial, sans-serif; margin: 35px; color: #222; }} .header {{ text-align: center; border-bottom: 3px double #111; padding-bottom: 10px; margin-bottom: 25px; }} .header h1 {{ margin: 0; font-size: 24px; font-weight: bold; }} .info-table {{ width: 100%; margin-bottom: 25px; border-collapse: collapse; }} .info-table td {{ padding: 9px; border: 1px solid #999; font-size: 13px; }} .info-table td.label {{ font-weight: bold; background-color: #f7f7f7; width: 20%; }} .section-title {{ font-size: 14px; font-weight: bold; margin-top: 25px; background-color: #111; color: #fff; padding: 6px 10px; }} .materials-table {{ width: 100%; border-collapse: collapse; margin-top: 5px; }} .materials-table th, .materials-table td {{ border: 1px solid #444; padding: 9px; font-size: 13px; }} .materials-table th {{ background-color: #dddddd; font-weight: bold; }} .signatures {{ margin-top: 70px; width: 100%; border-collapse: collapse; }} .signatures td {{ width: 50%; text-align: center; vertical-align: bottom; height: 50px; font-size: 12px; }} .line {{ border-top: 1px solid #333; width: 75%; margin: 0 auto 6px auto; }}</style></head><body><div class="header"><h1>A CASERNA DESDE 1977</h1><h2>ROMANEIO OPERACIONAL DE PRODUÇÃO</h2></div><table class="info-table"><tr><td rowspan="4" style="width: 140px; text-align: center; vertical-align: middle; padding: 5px; background-color: #fcfcfc;">{img_html}</td><td class="label">Código da OP:</td><td><strong>{id_op}</strong></td><td class="label">Status:</td><td>{status}</td></tr><tr><td class="label">Produto Final:</td><td>{prod}</td><td class="label">Grade / Tamanho:</td><td>{tam}</td></tr><tr><td class="label">Qtd Produzida:</td><td><strong>{qtd} un</strong></td><td class="label">Custo Geral Fechado:</td><td>R$ {custo_final:.2f}</td></tr><tr><td class="label">Custo Material:</td><td>R$ {custo_mat:.2f}</td><td class="label">Custo Mão de Obra:</td><td>R$ {custo_mo:.2f} ({tempo_gasto})</td></tr></table><div class="section-title">EXPLOSÃO DE MATERIAIS UTILIZADOS</div><table class="materials-table"><thead><tr><th>Descrição da Matéria-Prima / Insumo</th><th style="text-align: center;">Consumo Unit.</th><th style="text-align: center;">Qtd Total Requerida</th><th>Unidade</th><th style="text-align: center;">Conferido</th></tr></thead><tbody>{html_linhas}</tbody></table><table class="signatures"><tr><td><div class="line"></div>Responsável pela Separação</td><td><div class="line"></div>Responsável pelo Chão de Fábrica</td></tr></table><script>window.onload = function() {{ window.print(); }}</script></body></html>"""
                    st.write("")
                    st.download_button(label="🖨️ Imprimir Cópia Histórico", data=html_romaneio_hist, file_name=f"romaneio_{id_op}_hist.html", mime="text/html", key=f"print_hist_{id_op}")
    else:
        st.info("O histórico de OPs está vazio.")

# =============================================================================
# MÓDULO 5: CONTROLE DE ESTOQUE E VALORAÇÃO
# =============================================================================
elif menu == "📦 Estoque (Entradas/Saídas)":
    st.subheader("🔄 Movimentação e Valoração de Estoque")
    
    conn = conectar_db()
    df_insumos = pd.read_sql('SELECT nome AS "Insumo", unidade AS "Unidade", estoque AS "Qtd Atual", custo_unitario AS "Custo Médio (R$)" FROM insumos ORDER BY nome ASC', conn)
    df_visual_insumos = df_insumos.copy()
    df_visual_insumos['Custo Médio (R$)'] = df_visual_insumos['Custo Médio (R$)'].apply(lambda x: f"R$ {x:.2f}")
    conn.close()
    
    col_mov1, col_mov2 = st.columns(2)
    
    with col_mov1:
        with st.expander("➕ Lançar Entrada (Compra)", expanded=True):
            ins_ent = st.selectbox("Material comprado:", df_insumos['Insumo'].tolist(), key="sel_in")
            qtd_ent = st.number_input("Quantidade comprada:", min_value=0.0, step=1.0, key="qtd_in")
            val_ent = st.number_input("Valor TOTAL pago (R$):", min_value=0.0, step=10.0, key="val_in")
            
            alerta_preco = False
            ignorar_alerta = False
            
            if ins_ent and not df_insumos.empty:
                row_insumo = df_insumos[df_insumos['Insumo'] == ins_ent]
                c_atual = float(row_insumo.iloc[0]['Custo Médio (R$)']) if not row_insumo.empty else 0.0
                custo_unit_compra = val_ent / qtd_ent if qtd_ent > 0 else 0.0
                
                if custo_unit_compra > 0:
                    st.caption(f"💵 Custo Unitário calculado desta compra: **R$ {custo_unit_compra:.2f}**")
                    
                    if c_atual > 0 and (custo_unit_compra > c_atual * 2 or custo_unit_compra < c_atual / 2):
                        alerta_preco = True
                        st.error(f"⚠️ **Alerta de Digitação Crítico!** O valor unitário (R$ {custo_unit_compra:.2f}) está absurdamente diferente do histórico (R$ {c_atual:.2f}). Verifique pontos, vírgulas e zeros!")
                        ignorar_alerta = st.checkbox("Confirmo que a discrepância está correta.", key="ignorar_preco")
            
            st.write("---")
            conferido_entrada = st.checkbox("🔴 Confirmo que conferi a quantidade física e o valor total na nota fiscal.", key="conf_entrada")
            
            botao_desabilitado = not conferido_entrada or (alerta_preco and not ignorar_alerta)
                
            if st.button("Confirmar Entrada e Atualizar Custo", disabled=botao_desabilitado):
                if ins_ent and qtd_ent > 0 and val_ent >= 0:
                    conn = conectar_db()
                    cursor = conn.cursor()
                    cursor.execute("SELECT estoque, custo_unitario FROM insumos WHERE nome = %s", (ins_ent,))
                    est_atual, c_atual = cursor.fetchone()
                    novo_est = est_atual + qtd_ent
                    novo_custo_med = ((est_atual * c_atual) + val_ent) / novo_est if novo_est > 0 else 0.0
                    cursor.execute("UPDATE insumos SET estoque=%s, custo_unitario=%s WHERE nome=%s", (novo_est, novo_custo_med, ins_ent))
                    conn.commit()
                    conn.close()
                    st.success("Entrada registrada com sucesso!")
                    st.rerun()

    with col_mov2:
        with st.expander("➖ Lançar Saída (Ajuste / Perda)", expanded=True):
            ins_sai = st.selectbox("Material a retirar:", df_insumos['Insumo'].tolist(), key="sel_out")
            qtd_sai = st.number_input("Quantidade a subtrair:", min_value=0.0, step=1.0, key="qtd_out")
            
            if st.button("Confirmar Saída Manual"):
                if ins_sai and qtd_sai > 0:
                    conn = conectar_db()
                    cursor = conn.cursor()
                    cursor.execute("UPDATE insumos SET estoque = estoque - %s WHERE nome = %s", (qtd_sai, ins_sai))
                    conn.commit()
                    conn.close()
                    st.warning(f"Saída de {qtd_sai} registrada!")
                    st.rerun()

    st.write("---")
    st.write("📊 **Posição Financeira do Estoque de Matérias-Primas:**")
    st.dataframe(df_visual_insumos, use_container_width=True, hide_index=True)

# =============================================================================
# MÓDULO 6: CADASTRO E EDIÇÃO DE FICHAS TÉCNICAS
# =============================================================================
elif menu == "🛠️ Fichas Técnicas":
    conn = conectar_db()
    df_insumos = pd.read_sql("SELECT nome, unidade FROM insumos", conn)
    lista_disp = df_insumos['nome'].tolist()
    dict_unidades = dict(zip(df_insumos['nome'], df_insumos['unidade']))
    
    cursor = conn.cursor()
    cursor.execute("SELECT nome, grade, receita FROM produtos")
    fichas_cad = {p[0]: {"grade": json.loads(p[1]), "receita": json.loads(p[2])} for p in cursor.fetchall()}
    conn.close()
    
    acao_ficha = st.radio("Ação:", ["Novo Produto", "✏️ Editar Ficha Existente"], horizontal=True)
    
    if acao_ficha == "Novo Produto":
        st.subheader("2. Cadastrar Produto e Receita")
        col_c1, col_c2 = st.columns([2, 1])
        with col_c1:
            nome_p = st.text_input("Nome do Produto Final")
            grade_p = st.multiselect("Tamanhos:", ["PP", "P", "M", "G", "GG", "XG", "Único", "100cm", "110cm"])
            ins_sel = st.multiselect("Insumos desta receita:", lista_disp)
            receita_temp = {}
            if ins_sel:
                for i in ins_sel:
                    u = dict_unidades.get(i, "")
                    receita_temp[i] = {'quantidade': st.number_input(f"Consumo {i} ({u}):", min_value=0.0, step=0.1, format="%.2f", key=f"c_{i}"), 'unidade': u}
        with col_c2:
            foto_p = st.file_uploader("Foto do Produto", type=["png", "jpg", "jpeg"])

        if nome_p and grade_p and receita_temp:
            st.write("---")
            st.markdown("### 📋 Pré-visualização da Nova Engenharia")
            preview_nova = [{"Insumo": k, "Consumo Unitário": f"{v['quantidade']:.4f}", "Unidade": v['unidade']} for k, v in receita_temp.items()]
            st.dataframe(pd.DataFrame(preview_nova), use_container_width=True, hide_index=True)
            
            conferido_ficha_nova = st.checkbox("Confirmar que revisei as metragens e consumos da engenharia acima.", key="conf_f_nova")
            
            if st.button("Salvar Ficha", disabled=not conferido_ficha_nova):
                conn = conectar_db()
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO produtos (nome, grade, receita, foto) 
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (nome) DO UPDATE 
                    SET grade = EXCLUDED.grade, receita = EXCLUDED.receita, foto = EXCLUDED.foto
                """, (nome_p.upper(), json.dumps(grade_p), json.dumps(receita_temp), psycopg2.Binary(foto_p.getvalue()) if foto_p else None))
                conn.commit()
                conn.close()
                st.success("Ficha técnica salva com sucesso!")
                st.rerun()
                
    else:
        st.subheader("✏️ Alterar Engenharia de Produto")
        if not fichas_cad:
            st.info("Nenhum produto para editar.")
        else:
            p_edit = st.selectbox("Escolha o produto:", list(fichas_cad.keys()))
            dados_ant = fichas_cad[p_edit]
            
            col_e1, col_e2 = st.columns([2, 1])
            with col_e1:
                n_nome = st.text_input("Nome", value=p_edit)
                n_grade = st.multiselect("Tamanhos:", ["PP", "P", "M", "G", "GG", "XG", "Único", "100cm", "110cm"], default=dados_ant["grade"])
                ins_val = [i for i in list(dados_ant["receita"].keys()) if i in lista_disp]
                n_ins_sel = st.multiselect("Receita:", lista_disp, default=ins_val)
                r_edit = {}
                if n_ins_sel:
                    for i in n_ins_sel:
                        u = dict_unidades.get(i, "")
                        v_padrao = dados_ant["receita"].get(i, {}).get("quantidade", 0.0)
                        r_edit[i] = {'quantidade': st.number_input(f"Consumo {i} ({u}):", min_value=0.0, step=0.1, value=v_padrao, key=f"e_{i}"), 'unidade': u}
            with col_e2:
                n_foto = st.file_uploader("Substituir Foto", type=["png", "jpg", "jpeg"])

            if n_nome and n_grade and r_edit:
                st.write("---")
                st.markdown("### 📋 Pré-visualização das Alterações de Engenharia")
                preview_edicao = [{"Insumo": k, "Consumo Unitário": f"{v['quantidade']:.4f}", "Unidade": v['unidade']} for k, v in r_edit.items()]
                st.dataframe(pd.DataFrame(preview_edicao), use_container_width=True, hide_index=True)
                
                conferido_ficha_edit = st.checkbox("Confirmar que revisei as novas metragens alteradas.", key="conf_f_edit")

                col_b1, col_b2 = st.columns([1, 1])
                with col_b1:
                    if st.button("Salvar Alterações", disabled=not conferido_ficha_edit):
                        conn = conectar_db()
                        cursor = conn.cursor()
                        if n_nome.upper() != p_edit: 
                            cursor.execute("DELETE FROM produtos WHERE nome = %s", (p_edit,))
                        
                        if n_foto:
                            cursor.execute("""
                                INSERT INTO produtos (nome, grade, receita, foto) 
                                VALUES (%s, %s, %s, %s)
                                ON CONFLICT (nome) DO UPDATE 
                                SET grade = EXCLUDED.grade, receita = EXCLUDED.receita, foto = EXCLUDED.foto
                            """, (n_nome.upper(), json.dumps(n_grade), json.dumps(r_edit), psycopg2.Binary(n_foto.getvalue())))
                        else:
                            cursor.execute("SELECT foto FROM produtos WHERE nome = %s", (p_edit,))
                            row_f = cursor.fetchone()
                            f_ant = row_f[0] if row_f else None
                            
                            cursor.execute("""
                                INSERT INTO produtos (nome, grade, receita, foto) 
                                VALUES (%s, %s, %s, %s)
                                ON CONFLICT (nome) DO UPDATE 
                                SET grade = EXCLUDED.grade, receita = EXCLUDED.receita, foto = EXCLUDED.foto
                            """, (n_nome.upper(), json.dumps(n_grade), json.dumps(r_edit), f_ant))
                            
                        conn.commit()
                        conn.close()
                        st.success("Atualizado com sucesso!")
                        st.rerun()

                with col_b2:
                    if st.button("🗑️ Excluir Produto"):
                        conn = conectar_db()
                        cursor = conn.cursor()
                        cursor.execute("DELETE FROM produtos WHERE nome = %s", (p_edit,))
                        conn.commit()
                        conn.close()
                        st.rerun()

# =============================================================================
# MÓDULO 7: CADASTRO E EDIÇÃO DE INSUMOS
# =============================================================================
elif menu == "⚙️ Cadastro de Insumos":
    conn = conectar_db()
    df_insumos = pd.read_sql("SELECT nome, unidade FROM insumos", conn)
    lista_ins = df_insumos['nome'].tolist()
    dict_unidades = dict(zip(df_insumos['nome'], df_insumos['unidade']))
    conn.close()

    acao_ins = st.radio("Ação matéria-prima:", ["Cadastrar Novo Insumo", "✏️ Editar Insumo Existente"], horizontal=True)

    if acao_ins == "Cadastrar Novo Insumo":
        st.subheader("1. Cadastrar Matéria-Prima")
        col_i1, col_i2 = st.columns(2)
        with col_i1:
            nome_i = st.text_input("Nome do Insumo")
        with col_i2:
            unidade_i = st.selectbox("Unidade", ["Unidades", "Metros", "Rolos", "Kg", "Pares"])
            
        if st.button("Salvar Insumo"):
            if nome_i:
                conn = conectar_db()
                cursor = conn.cursor()
                try:
                    cursor.execute("INSERT INTO insumos VALUES (%s, %s, 0.0, 0.0)", (nome_i.upper(), unidade_i))
                    conn.commit()
                    st.success("Cadastrado!")
                except psycopg2.IntegrityError:
                    st.error("Já cadastrado!")
                finally:
                    conn.close()
                st.rerun()
    else:
        st.subheader("✏️ Modificar Insumo")
        if not lista_ins:
            st.info("Nenhum insumo.")
        else:
            ins_edit = st.selectbox("Selecione:", lista_ins)
            
            u_atual = dict_unidades.get(ins_edit, "Unidades")
            
            c_ed1, c_ed2 = st.columns(2)
            u_lista = ["Unidades", "Metros", "Rolos", "Kg", "Pares"]
            with c_ed1:
                n_nome_i = st.text_input("Nome", value=ins_edit)
            with c_ed2:
                n_uni_i = st.selectbox("Unidade", u_lista, index=u_lista.index(u_atual) if u_atual in u_lista else 0)
                
            st.write("---")
            c_bi1, c_bi2 = st.columns([1, 1])
            with c_bi1:
                if st.button("Salvar Alterações"):
                    if n_nome_i:
                        conn = conectar_db()
                        cursor = conn.cursor()
                        cursor.execute("UPDATE insumos SET nome=%s, unidade=%s WHERE nome=%s", (n_nome_i.upper(), n_uni_i, ins_edit))
                        conn.commit()
                        conn.close()
                        st.rerun()
            with c_bi2:
                if st.button("🗑️ Excluir Insumo"):
                    conn = conectar_db()
                    cursor = conn.cursor()
                    cursor.execute("DELETE FROM insumos WHERE nome=%s", (ins_edit,))
                    conn.commit()
                    conn.close()
                    st.rerun()
