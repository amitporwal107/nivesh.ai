package ai.nivesh.app.ui.protrader;

import ai.nivesh.app.data.repo.PositionalRepository;
import dagger.internal.DaggerGenerated;
import dagger.internal.Factory;
import dagger.internal.QualifierMetadata;
import dagger.internal.ScopeMetadata;
import javax.annotation.processing.Generated;
import javax.inject.Provider;

@ScopeMetadata
@QualifierMetadata
@DaggerGenerated
@Generated(
    value = "dagger.internal.codegen.ComponentProcessor",
    comments = "https://dagger.dev"
)
@SuppressWarnings({
    "unchecked",
    "rawtypes",
    "KotlinInternal",
    "KotlinInternalInJava"
})
public final class ProTraderViewModel_Factory implements Factory<ProTraderViewModel> {
  private final Provider<PositionalRepository> repoProvider;

  public ProTraderViewModel_Factory(Provider<PositionalRepository> repoProvider) {
    this.repoProvider = repoProvider;
  }

  @Override
  public ProTraderViewModel get() {
    return newInstance(repoProvider.get());
  }

  public static ProTraderViewModel_Factory create(Provider<PositionalRepository> repoProvider) {
    return new ProTraderViewModel_Factory(repoProvider);
  }

  public static ProTraderViewModel newInstance(PositionalRepository repo) {
    return new ProTraderViewModel(repo);
  }
}
