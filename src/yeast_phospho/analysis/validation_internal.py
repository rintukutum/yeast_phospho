#!/usr/bin/env python
# Copyright (C) 2016  Emanuel Goncalves

import numpy as np
import seaborn as sns
import matplotlib.pyplot as plt
from pandas import read_csv, DataFrame, Series
from scipy.stats.stats import spearmanr, pearsonr, ttest_ind
from yeast_phospho.utilities import get_metabolites_name


# -- Imports
# Associations
assoc_tf = read_csv('./tables/supp_table3_tf_metabolites.csv')
assoc_tf['type'] = 'Transcription-factor'

assoc_kp = read_csv('./tables/supp_table3_kp_metabolites.csv')
assoc_kp['type'] = 'Kinase/Phosphatase'

assoc = assoc_tf.append(assoc_kp)
assoc['ion'] = ['%.2f' % i for i in assoc['ion']]
print 'assoc', assoc.shape


# -- Metabolomics
met_name = get_metabolites_name()
met_name = {'%.4f' % float(k): met_name[k] for k in met_name if len(met_name[k].split('; ')) == 1}

metabolomics = read_csv('./tables/metabolomics_steady_state_no_growth.tab', sep='\t', index_col=0)
metabolomics = metabolomics[metabolomics.std(1) > .4]
metabolomics.index = ['%.2f' % i for i in metabolomics.index]

dup = Series(dict(zip(*(np.unique(metabolomics.index, return_counts=True))))).sort_values()
metabolomics = metabolomics.drop(dup[dup > 1].index, axis=0)
print 'metabolomics', metabolomics.shape


# --
val_df = []
for ion, feature, coef, type in assoc[['ion', 'feature', 'coef', 'type']].values:
    if ion in metabolomics.index and feature in metabolomics.columns:
        metabolite_zscore = metabolomics.ix[ion, feature]
        coef_discrete = 'Negative' if coef < 0 else 'Positive'

        res = {'feature': feature, 'ion': ion, 'coef': coef, 'coef_binary': coef_discrete, 'zscore': metabolite_zscore, 'type': type}
        val_df.append(res)
        print res


val_df = DataFrame(val_df)
val_df.to_csv('./tables/validations_internal.csv', index=False)
print val_df


# Plot
plot_df = val_df[val_df['coef'].abs() > .1]
print plot_df

t, pval = ttest_ind(
    plot_df.loc[(plot_df['coef_binary'] == 'Negative'), 'zscore'],
    plot_df.loc[(plot_df['coef_binary'] == 'Positive'), 'zscore']
)
print t, pval

# Plot
sns.set(style='ticks', font_scale=.75, rc={'axes.linewidth': .3, 'xtick.major.width': .3, 'ytick.major.width': .3, 'lines.linewidth': .75})
sns.boxplot('coef_binary', 'zscore', data=plot_df, color='#808080', sym='')
sns.stripplot('coef_binary', 'zscore', data=plot_df, color='#808080', edgecolor='white', linewidth=.3, jitter=.2)
plt.axhline(0, ls='-', lw=.1, c='gray')
sns.despine()
plt.xlabel('Association')
plt.ylabel('Metabolite (zscore)')
plt.title('Feature knockdown\n(p-value %.2e)' % pval)
plt.gcf().set_size_inches(1.5, 3)
plt.legend(loc=4)
plt.savefig('./reports/associations_metabolomics_cor_boxplots_internal.pdf', bbox_inches='tight')
plt.close('all')
print '[INFO] Plot done'