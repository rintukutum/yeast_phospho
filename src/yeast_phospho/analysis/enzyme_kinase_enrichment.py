import pickle
import numpy as np
import seaborn as sns
import matplotlib.pyplot as plt
import matplotlib.ticker as mtick
import statsmodels.api as sm
import itertools as it
from yeast_phospho import wd
from scipy.stats.stats import pearsonr
from sklearn.metrics import roc_curve, auc
from scipy.stats.distributions import hypergeom
from pymist.reader.sbml_reader import read_sbml_model
from pandas import DataFrame, read_csv, pivot_table, melt, Series
from sklearn.cross_validation import LeaveOneOut, ShuffleSplit
from sklearn.feature_selection import SelectKBest, f_regression
from sklearn.metrics.pairwise import euclidean_distances, manhattan_distances, linear_kernel
from yeast_phospho.utilities import metric, pearson, get_proteins_name, get_metabolites_name


# -- Import metabolic model ion mapping
annot = read_csv('%s/files/Annotation_Yeast_glucose.csv' % wd, sep=',', index_col=1)
annot['mz'] = ['%.4f' % round(i, 2) for i in annot['mz']]
annot = annot['mz'].to_dict()


# -- Import metabolic model
model = read_sbml_model('/Users/emanuel/Projects/resources/metabolic_models/iMM904.v1.xml')

# Remove extracellular metabolites
s_matrix = model.get_stoichiometric_matrix()
s_matrix = s_matrix[[not i.endswith('_b') for i in s_matrix.index]]

# Remove biomass reactions
s_matrix = s_matrix.drop('R_biomass_SC5_notrace', axis=1)

# Build {metabolite: protein} dict & Filter highly connected metabolites
m_dict = {i: {r for r in s_matrix.loc[i, s_matrix.ix[i] != 0].index if not r.startswith('R_EX_')} for i in s_matrix.index}
m_dict = {m: {g for r in m_dict[m] for g in model.get_reaction_genes(r)} for m in m_dict}
m_dict = {m: {g for x in m_dict if x[2:-2] == m for g in m_dict[x]} for m in annot}
m_dict = {m: m_dict[m] for m in m_dict if 0 < len(m_dict[m]) < 5}

# Build {protein: metabolite} dict
m_genes = {g for m in m_dict for g in m_dict[m]}
g_dict = {g: {m for m in m_dict if g in m_dict[m]} for g in m_genes}

# Build {protein: ion} dict
i_dict = {g: {annot[m] for m in g_dict[g]} for g in g_dict}


# -- Read protein interactions dbs
dbs = {}
for bkg_type in ['biogrid', 'string']:
    if bkg_type == 'biogrid':
        db = read_csv(wd + 'files/BIOGRID-ORGANISM-Saccharomyces_cerevisiae_S288c-3.4.127.tab', sep='\t', skiprows=35)[['INTERACTOR_A', 'INTERACTOR_B']]
        db = {(s, t) for s, t in db.values}

    elif bkg_type == 'string':
        db = read_csv(wd + 'files/4932.protein.links.v9.1.txt', sep=' ')

        thres = 600
        db = db[db['combined_score'] > thres]

        db = {(source.split('.')[1], target.split('.')[1]) for source, target in db[['protein1', 'protein2']].values}

        print 'thres: %.2f' % thres

    db = {(p1, p2) for p1, p2 in db if p1 != p2}
    print '[INFO] %s: %d' % (bkg_type, len(db))

    db = {(s, i) for p1, p2 in db for s, t in it.permutations((p1, p2), 2) if t in i_dict for i in i_dict[t]}
    print '[INFO] %s, only enzymatic reactions: %d' % (bkg_type, len(db))

    dbs[bkg_type] = db

db = dbs['biogrid'].union(dbs['string'])
db_proteins = {i[0] for i in db}
db_ions = {i[1] for i in db}
print '[INFO] Kinase/Enzymes interactions data-bases imported'

# -- Import data-sets
# Dynamic without growth
metabolomics_dyn_ng = read_csv('%s/tables/metabolomics_dynamic_no_growth.tab' % wd, sep='\t', index_col=0)
metabolomics_dyn_ng = metabolomics_dyn_ng[metabolomics_dyn_ng.std(1) > .4]
metabolomics_dyn_ng.index = ['%.4f' % i for i in metabolomics_dyn_ng.index]

k_activity_dyn_ng = read_csv('%s/tables/kinase_activity_dynamic_gsea_no_growth.tab' % wd, sep='\t', index_col=0)
k_activity_dyn_ng = k_activity_dyn_ng[(k_activity_dyn_ng.count(1) / k_activity_dyn_ng.shape[1]) > .75].replace(np.NaN, 0.0)

tf_activity_dyn_ng = read_csv('%s/tables/tf_activity_dynamic_gsea_no_growth.tab' % wd, sep='\t', index_col=0)
tf_activity_dyn_ng = tf_activity_dyn_ng[tf_activity_dyn_ng.std(1) > .4]


# -- Define comparisons
comparisons = [
    (tf_activity_dyn_ng, metabolomics_dyn_ng, 'TFs', 'Dynamic', 'without'),
    (k_activity_dyn_ng, metabolomics_dyn_ng, 'Kinases', 'Dynamic', 'without'),
]


# -- Perform kinase/enzyme enrichment
sns.set(style='ticks', context='paper')
(f, plot), pos = plt.subplots(len(comparisons), 1, figsize=(4, 4. * len(comparisons))), 0
for xs, ys, ft, dt, gt in comparisons:
    # Define variables
    conditions = list(set(xs).intersection(ys))
    experiments = {'_'.join(c.split('_')[:-1]) for c in conditions}
    description = ' '.join([ft, dt, gt])

    #
    lm_res = {}
    for m in ys.index:
        m_coef = {}

        iteration = 0
        for exp in experiments:
            train = [c for c in conditions if not c.startswith(exp)]
            test = [c for c in conditions if c.startswith(exp)]

            yss, xss = ys.ix[m, train], xs[train].T

            fs = SelectKBest(k=15, score_func=f_regression).fit(xss, yss)
            xss = xss.loc[:, fs.get_support()]
            xss['const'] = 1

            lm = sm.OLS(yss, xss).fit_regularized(L1_wt=0, alpha=0.1)

            xss = xs.ix[fs.get_support(), test].T
            xss['const'] = 1

            pred, meas = lm.predict(xss), ys.ix[m, test]

            cor, pval = pearsonr(list(pred), list(meas))

            m_coef['%d' % iteration] = (-np.log10(lm.pvalues.drop('const'))).to_dict()

            iteration += 1

        lm_res[m] = DataFrame(m_coef).mean(1).to_dict()
    print '[INFO] Associations performed'

    # Conditions betas
    info_table = DataFrame([(f, m, lm_res[m][f]) for m in lm_res for f in lm_res[m]], columns=['feature', 'metabolite', 'coef'])

    #
    info_table = info_table[[i in db_proteins for i in info_table['feature']]]
    info_table = info_table[[i in db_ions for i in info_table['metabolite']]]

    # Kinase/Enzyme interactions via metabolite correlations
    info_table['TP'] = [int(i in db) for i in zip(info_table['feature'], info_table['metabolite'])]

    info_table = info_table.dropna()
    print '[INFO] TP (%s): %d / %d' % (description, info_table['TP'].sum(), info_table.shape[0])

    # Plot Kinase/Enzyme enrichment
    # ROC plot analysis
    ax = plot[pos]
    for roc_metric in ['coef']:
        curve_fpr, curve_tpr, thresholds = roc_curve(info_table['TP'], info_table[roc_metric])
        curve_auc = auc(curve_fpr, curve_tpr)

        ax.plot(curve_fpr, curve_tpr, label='%s (area = %0.2f)' % (roc_metric, curve_auc))

    ax.plot([0, 1], [0, 1], 'k--')
    ax.set_ylabel(description)
    sns.despine(trim=True, ax=ax)
    ax.legend(loc='lower right')

    pos += 1

plt.savefig('%s/reports/kinase_enzyme_enrichment_metabolomics.pdf' % wd, bbox_inches='tight')
plt.close('all')
print '[INFO] Plotting done: %s/reports/kinase_enzyme_enrichment_metabolomics.pdf' % wd
