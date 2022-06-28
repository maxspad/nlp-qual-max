from importlib_metadata import version
import pandas as pd

# Spacy NLP / sklearn
from ..skspacy import SpacyTokenFilter, SpacyDocFeats
from sklearn.pipeline import Pipeline
from sklearn.compose import ColumnTransformer
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.svm import LinearSVC
from sklearn.preprocessing import MinMaxScaler
from sklearn.model_selection import cross_validate
import sklearn.metrics as mets

# configuration management
import hydra
from omegaconf import DictConfig, OmegaConf
import logging
log = logging.getLogger(__name__)

# mlflow
import mlflow

CONF_PATH = '../../'
CONF_FOLDER = 'conf'
CONF_NAME = 'config'
CONF_FILE = f'{CONF_FOLDER}/{CONF_NAME}.yaml'

@hydra.main(version_base=None, config_path=f'{CONF_PATH}/{CONF_FOLDER}', config_name=CONF_NAME)
def main(cfg : DictConfig):
    cfg = cfg.train 

    mlflow.set_experiment(experiment_name=cfg.mlflow_experiment_name)
    with mlflow.start_run():
        log.info('Training model...')
        log.debug(f"Parameters:\n{OmegaConf.to_yaml(cfg)}")
        mlflow.log_params(OmegaConf.to_object(cfg))
        
        log.info(f'Loading data from {cfg.train_path}')
        df = pd.read_pickle(cfg.train_path)
        log.info(f'Data is shape {df.shape}')
        log.info(f'There are {df[cfg.text_var].isna().sum()} blanks in {cfg.text_var}, dropping')
        log.info(f'There are {df[cfg.target_var].isna().sum()} blanks in {cfg.target_var}, dropping')
        df = df.dropna(subset=[cfg.text_var, cfg.target_var])
        log.debug(f'Data head\n{df.head()}')

        X = df[cfg.text_var].values.copy()[:, None]
        y = df[cfg.target_var].values.copy()
        y = y + 1
        y[y == 2] = 0
        log.debug(f'X shape {X.shape} / y shape {y.shape}')

        mdl = LinearSVC(C=cfg.model_c, class_weight=cfg.class_weight, random_state=cfg.random_seed)
        pipe = Pipeline((
            ('ct', ColumnTransformer((
                ('bowpipe', Pipeline((
                    ('tokfilt', SpacyTokenFilter(punct=cfg.punct, lemma=cfg.lemma, stop=cfg.stop, pron=cfg.pron)),
                    ('vec', CountVectorizer(max_df=cfg.max_df, min_df=cfg.min_df, ngram_range=(cfg.ngram_min, cfg.ngram_max))),
                )), [0]),
                ('docfeatspipe', Pipeline((
                    ('docfeats', SpacyDocFeats(token_count=cfg.token_count, pos_counts=cfg.pos_counts, ent_counts=cfg.ent_counts, vectors=cfg.vectors)),
                    ('scaler', MinMaxScaler())
                )), [0])
            ))),
            ('mdl', mdl)
        ))
        log.debug(f'Pipeline is\n{pipe}')


        log.info('Cross validating model...')
        res = cross_validate(pipe, X, y, scoring=_model_scorer, cv=5, n_jobs=1)

        res = pd.DataFrame(res)
        res_mn = pd.DataFrame(res.mean()).T.rename(lambda x: 'mean_' + x, axis=1)
        res_std = pd.DataFrame(res.std()).T.rename(lambda x: 'std_' + x, axis=1)
        mlflow.log_metrics(res_mn.iloc[0,:].to_dict())
        mlflow.log_metrics(res_std.iloc[0,:].to_dict())
        log.info(f'Cross validation results:\n{res}\n{res_mn}\n{res_std}')

        mlflow.log_text(res.to_csv(),'fold_results.csv')
        mlflow.log_text(res_mn.to_csv(),'res_mn.csv')
        mlflow.log_text(res_std.to_csv(),'res_std.csv')
        mlflow.log_artifact(cfg.conda_yaml_path)
        mlflow.log_artifact(CONF_FILE)

        log.info('Fitting final model...')
        pipe.fit(X, y)     
        log.info('Saving final model...')   
        mlflow.sklearn.log_model(pipe, 'model')

def _model_scorer(clf, X, y):
    p = clf.predict(X)
    s = clf.decision_function(X)
    cm = mets.confusion_matrix(y, p)

    return {
        'balanced_accuracy': mets.balanced_accuracy_score(y, p),
        'accuracy': mets.accuracy_score(y, p),
        'roc_auc': mets.roc_auc_score(y, s),
        'f1': mets.f1_score(y, p),
        'precision': mets.precision_score(y, p),
        'recall': mets.recall_score(y, p),
        'tp': cm[0,0],
        'tn': cm[1,1],
        'fp': cm[0,1],
        'fn': cm[1,0],
        # 'confusion': mets.confusion_matrix(y, p),
        # 'clfrep': mets.classification_report(y, p)
    }

if __name__ == "__main__":
    main()