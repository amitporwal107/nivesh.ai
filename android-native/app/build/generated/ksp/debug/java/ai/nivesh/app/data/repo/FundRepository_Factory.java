package ai.nivesh.app.data.repo;

import ai.nivesh.app.data.api.NiveshApi;
import dagger.internal.DaggerGenerated;
import dagger.internal.Factory;
import dagger.internal.QualifierMetadata;
import dagger.internal.ScopeMetadata;
import javax.annotation.processing.Generated;
import javax.inject.Provider;

@ScopeMetadata("javax.inject.Singleton")
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
public final class FundRepository_Factory implements Factory<FundRepository> {
  private final Provider<NiveshApi> apiProvider;

  public FundRepository_Factory(Provider<NiveshApi> apiProvider) {
    this.apiProvider = apiProvider;
  }

  @Override
  public FundRepository get() {
    return newInstance(apiProvider.get());
  }

  public static FundRepository_Factory create(Provider<NiveshApi> apiProvider) {
    return new FundRepository_Factory(apiProvider);
  }

  public static FundRepository newInstance(NiveshApi api) {
    return new FundRepository(api);
  }
}
