package ai.nivesh.app.ui.portfolio;

import ai.nivesh.app.data.repo.PortfolioRepository;
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
public final class PortfolioViewModel_Factory implements Factory<PortfolioViewModel> {
  private final Provider<PortfolioRepository> repoProvider;

  public PortfolioViewModel_Factory(Provider<PortfolioRepository> repoProvider) {
    this.repoProvider = repoProvider;
  }

  @Override
  public PortfolioViewModel get() {
    return newInstance(repoProvider.get());
  }

  public static PortfolioViewModel_Factory create(Provider<PortfolioRepository> repoProvider) {
    return new PortfolioViewModel_Factory(repoProvider);
  }

  public static PortfolioViewModel newInstance(PortfolioRepository repo) {
    return new PortfolioViewModel(repo);
  }
}
